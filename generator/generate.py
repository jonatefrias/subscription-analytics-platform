"""Synthetic source data for a fictional sports-streaming subscription app ("Matchday+").

The goal is not volume but *realistic behaviour and realistic mess*, so the dbt
project has real problems to solve:

Behaviour that is simulated on purpose (and can be rediscovered in the marts):
  * seasonality: signups peak at season start, churn spikes in the off-season (Jun-Jul)
  * event-driven acquisition: big match days bring 5x signups that churn faster
  * a monthly price increase on 2025-07-01 in US/MX/ES, with a churn bump right after
  * trials (7 days) on monthly plans, annual plans without trial
  * failed payments with one retry, ending in involuntary churn
  * reactivations, and monthly -> annual plan switches
  * a paywall A/B test in Mar-Apr 2026 that highlights the annual plan
  * latent engagement per customer that drives both playback and churn

Source quirks injected on purpose (handled in the staging layer):
  * the CRM export repeats a customer row every time the profile is updated
  * country codes with mixed case and stray whitespace
  * ~4% of customers without acquisition channel
  * app-store payments report the currency in lowercase
  * the playback stream is at-least-once: ~0.5% duplicated event ids
  * a few playback events with negative or missing watch time
  * playback timestamps arrive as ISO-8601 strings

Usage:
    python generator/generate.py --out data/raw --seed 42
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

START = dt.date(2024, 1, 1)
END = dt.date(2026, 10, 31)  # last day with data; "as of" is END + 1 day 00:00 UTC
AS_OF = dt.datetime.combine(END + dt.timedelta(days=1), dt.time())

# market -> currency, share of signups, monthly price, annual price (local currency)
MARKETS = {
    "US": ("USD", 0.30, 9.99, 99.99),
    "MX": ("MXN", 0.20, 149.00, 1490.00),
    "ES": ("EUR", 0.12, 8.99, 89.99),
    "AR": ("USD", 0.10, 5.99, 59.99),  # LatAm digital goods are often priced in USD
    "CL": ("CLP", 0.10, 6990.00, 69900.00),
    "CO": ("COP", 0.10, 29900.00, 299000.00),
    "PE": ("PEN", 0.08, 29.90, 299.00),
}
PRICE_INCREASE_DATE = dt.date(2025, 7, 1)
NEW_MONTHLY_PRICE = {"US": 11.99, "MX": 169.00, "ES": 9.99}
FX_START = {"USD": 1.0, "MXN": 18.5, "EUR": 0.92, "CLP": 940.0, "COP": 4050.0, "PEN": 3.75}

PLATFORMS = (["web", "ios", "android", "tv"], [0.45, 0.25, 0.20, 0.10])
CHANNELS = (
    ["paid_social", "paid_search", "organic", "referral", "partner"],
    [0.30, 0.20, 0.30, 0.10, 0.10],
)
PAID_CHANNEL_CAC_USD = {"paid_social": 18.0, "paid_search": 14.0, "partner": 9.0}
MARKET_CAC_FACTOR = {"US": 1.6, "ES": 1.3, "MX": 0.8, "AR": 0.6, "CL": 0.6, "CO": 0.6, "PE": 0.6}

SIGNUP_SEASONALITY = {1: 1.1, 2: 1.2, 3: 1.2, 4: 1.1, 5: 1.0, 6: 0.6, 7: 0.6, 8: 1.3, 9: 1.1, 10: 1.0, 11: 1.0, 12: 0.8}
CHURN_SEASONALITY = {6: 1.7, 7: 1.6, 12: 1.2}
BIG_MATCH_DAYS = {
    dt.date(2024, 3, 17), dt.date(2024, 5, 25), dt.date(2024, 8, 17), dt.date(2024, 10, 27), dt.date(2024, 12, 8),
    dt.date(2025, 3, 16), dt.date(2025, 5, 31), dt.date(2025, 8, 16), dt.date(2025, 10, 26), dt.date(2025, 12, 7),
    dt.date(2026, 3, 15), dt.date(2026, 5, 30), dt.date(2026, 8, 15), dt.date(2026, 10, 25),
}
EXPERIMENT = {
    "experiment_id": "paywall_annual_highlight",
    "start": dt.date(2026, 3, 1),
    "end": dt.date(2026, 4, 30),
}


def add_months(d: dt.date, months: int) -> dt.date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def ts(d: dt.date, rng: np.random.Generator) -> dt.datetime:
    """A random timestamp within day `d`."""
    return dt.datetime.combine(d, dt.time()) + dt.timedelta(seconds=int(rng.integers(0, 86_400)))


@dataclass
class Sink:
    customers: list = field(default_factory=list)
    subscriptions: list = field(default_factory=list)
    payments: list = field(default_factory=list)
    assignments: list = field(default_factory=list)
    access: list = field(default_factory=list)  # (customer_id, from, to, engagement) for playback


class Simulator:
    def __init__(self, seed: int, scale: float):
        self.rng = np.random.default_rng(seed)
        self.scale = scale
        self.out = Sink()
        self.sub_seq = 0
        self.pay_seq = 0

    # ------------------------------------------------------------------ prices
    def monthly_price(self, market: str, on: dt.date) -> float:
        if market in NEW_MONTHLY_PRICE and on >= PRICE_INCREASE_DATE:
            return NEW_MONTHLY_PRICE[market]
        return MARKETS[market][2]

    def price(self, market: str, period: str, on: dt.date) -> float:
        return self.monthly_price(market, on) if period == "monthly" else MARKETS[market][3]

    # ----------------------------------------------------------------- signups
    def daily_signups(self, d: dt.date) -> int:
        years = (d - START).days / 365.25
        lam = 55 * self.scale * (1.25 ** years) * SIGNUP_SEASONALITY[d.month]
        if d.weekday() >= 5:
            lam *= 1.4
        if d in BIG_MATCH_DAYS:
            lam *= 5
        return int(self.rng.poisson(lam))

    def run(self) -> Sink:
        customer_id = 0
        d = START
        while d <= END:
            for _ in range(self.daily_signups(d)):
                customer_id += 1
                self.new_customer(customer_id, d)
            d += dt.timedelta(days=1)
        return self.out

    def new_customer(self, cid: int, d: dt.date) -> None:
        rng = self.rng
        markets = list(MARKETS)
        market = rng.choice(markets, p=[MARKETS[m][1] for m in markets])
        platform = rng.choice(PLATFORMS[0], p=PLATFORMS[1])
        channel = rng.choice(CHANNELS[0], p=CHANNELS[1])
        created_at = ts(d, rng)
        customer = {
            "customer_id": f"c_{cid:06d}",
            "created_at": created_at,
            "country": str(market),
            "signup_platform": str(platform),
            "acquisition_channel": str(channel),
            "engagement": float(rng.lognormal(0.0, 0.6)),
            "big_match_signup": d in BIG_MATCH_DAYS,
        }
        self.out.customers.append(customer)

        annual_share = 0.15
        conversion_shift = 0.0
        if platform == "web" and EXPERIMENT["start"] <= d <= EXPERIMENT["end"]:
            variant = "annual_highlight" if rng.random() < 0.5 else "control"
            self.out.assignments.append({
                "experiment_id": EXPERIMENT["experiment_id"],
                "customer_id": customer["customer_id"],
                "variant": variant,
                "assigned_at": created_at,
            })
            if variant == "annual_highlight":
                annual_share, conversion_shift = 0.26, -0.03
        period = "annual" if rng.random() < annual_share else "monthly"
        self.subscribe(customer, d, period, trial=(period == "monthly"), conversion_shift=conversion_shift)

    # ------------------------------------------------------------ lifecycle
    def provider(self, customer: dict) -> str:
        return {"ios": "apple", "android": "google"}.get(customer["signup_platform"], "stripe")

    def churn_hazard(self, customer: dict, period: str, billing_date: dt.date, tenure: int) -> float:
        if period == "annual":
            return 0.35
        h = 0.07 * CHURN_SEASONALITY.get(billing_date.month, 1.0)
        h *= {"paid_social": 1.25, "partner": 1.15, "referral": 0.8}.get(customer["acquisition_channel"], 1.0)
        h *= 1.4 if tenure <= 3 else (0.7 if tenure > 12 else 1.0)
        h *= 1.3 if customer["big_match_signup"] and tenure <= 3 else 1.0
        if customer["country"] in NEW_MONTHLY_PRICE and PRICE_INCREASE_DATE <= billing_date < add_months(PRICE_INCREASE_DATE, 2):
            h *= 1.5
        h *= customer["engagement"] ** -0.5
        return min(h, 0.9)

    def subscribe(self, customer: dict, start: dt.date, period: str, trial: bool,
                  conversion_shift: float = 0.0, depth: int = 0) -> None:
        if start > END or depth > 6:
            return
        rng = self.rng
        self.sub_seq += 1
        sub_id = f"s_{self.sub_seq:07d}"
        market = customer["country"]
        sub = {
            "subscription_id": sub_id,
            "customer_id": customer["customer_id"],
            "plan_id": f"{market.lower()}_{period}",
            "payment_provider": self.provider(customer),
            "started_at": ts(start, rng) if depth else customer["created_at"],
            "trial_end_at": None,
            "canceled_at": None,
            "ended_at": None,
            "cancel_reason": None,
        }
        self.out.subscriptions.append(sub)
        paid_start = start

        if trial:
            trial_end = start + dt.timedelta(days=7)
            sub["trial_end_at"] = dt.datetime.combine(trial_end, sub["started_at"].time())
            if trial_end > END:  # still trialing at the as-of date
                self.access(customer, start, END)
                return
            p_convert = 0.58 + conversion_shift
            p_convert += {"paid_social": -0.10, "referral": 0.10}.get(customer["acquisition_channel"], 0.0)
            p_convert += 0.05 if customer["signup_platform"] == "tv" else 0.0
            if rng.random() > p_convert:
                cancel_day = start + dt.timedelta(days=int(rng.choice(7, p=[.05, .05, .05, .1, .15, .25, .35])))
                self.end(sub, cancel_day, trial_end, "trial_not_converted")
                self.access(customer, start, trial_end)
                if rng.random() < 0.06:
                    self.reactivate(customer, trial_end, depth, mean_gap=150)
                return
            paid_start = trial_end

        period_start, tenure = paid_start, 0
        while period_start <= END:
            tenure += 1
            amount = self.price(market, period, period_start)
            fail_p = 0.05 if sub["payment_provider"] == "stripe" else 0.03
            if rng.random() < fail_p:
                self.payment(sub, period_start, amount, "failed", attempt=1)
                retry = period_start + dt.timedelta(days=3)
                if rng.random() < 0.55 and retry <= END:
                    self.payment(sub, retry, amount, "paid", attempt=2, period_start=period_start)
                else:
                    if retry <= END:
                        self.end(sub, retry, retry, "payment_failed")
                        self.access(customer, start, retry)
                        if rng.random() < 0.30:
                            self.reactivate(customer, retry, depth, mean_gap=20)
                    else:
                        self.access(customer, start, END)
                    return
            else:
                self.payment(sub, period_start, amount, "paid", attempt=1)

            period_end = add_months(period_start, 1 if period == "monthly" else 12)
            if rng.random() < self.churn_hazard(customer, period, period_start, tenure):
                span = max((period_end - period_start).days - 1, 1)
                cancel_day = period_start + dt.timedelta(days=int(rng.integers(0, span)))
                if cancel_day > END:  # the cancellation has not happened yet
                    break
                self.end(sub, cancel_day, period_end, "voluntary")
                self.access(customer, start, min(period_end, END))
                if rng.random() < 0.22:
                    self.reactivate(customer, period_end, depth, mean_gap=120)
                return
            if period == "monthly" and tenure >= 2 and rng.random() < 0.012 and period_end <= END:
                self.end(sub, period_end - dt.timedelta(days=1), period_end, "plan_change")
                self.access(customer, start, period_end)
                self.subscribe(customer, period_end, "annual", trial=False, depth=depth + 1)
                return
            period_start = period_end
        self.access(customer, start, END)

    def end(self, sub: dict, cancel_day: dt.date, end_day: dt.date, reason: str) -> None:
        sub["canceled_at"] = ts(cancel_day, self.rng)
        sub["ended_at"] = dt.datetime.combine(end_day, sub["started_at"].time())
        sub["cancel_reason"] = reason

    def reactivate(self, customer: dict, after: dt.date, depth: int, mean_gap: float) -> None:
        gap = int(10 + self.rng.exponential(mean_gap))
        period = "annual" if self.rng.random() < 0.10 else "monthly"
        self.subscribe(customer, after + dt.timedelta(days=gap), period, trial=False, depth=depth + 1)

    def payment(self, sub: dict, on: dt.date, amount: float, status: str, attempt: int,
                period_start: dt.date | None = None) -> None:
        self.pay_seq += 1
        refunded_at = None
        if status == "paid" and self.rng.random() < 0.008:
            refunded_at = ts(on + dt.timedelta(days=int(self.rng.integers(1, 6))), self.rng)
        self.out.payments.append({
            "payment_id": f"p_{self.pay_seq:08d}",
            "subscription_id": sub["subscription_id"],
            "attempt": attempt,
            "status": status,
            "amount": amount,
            "currency": MARKETS[sub["plan_id"].split("_")[0].upper()][0],
            "billed_at": ts(on, self.rng),
            "period_start": period_start or on,
            "refunded_at": refunded_at,
            "provider": sub["payment_provider"],
        })

    def access(self, customer: dict, start: dt.date, end: dt.date) -> None:
        self.out.access.append((customer["customer_id"], start, min(end, END), customer["engagement"]))


# ---------------------------------------------------------------- side tables
def build_plans() -> tuple[pd.DataFrame, pd.DataFrame]:
    plans, prices = [], []
    for market, (currency, _, monthly, annual) in MARKETS.items():
        for period, price in (("monthly", monthly), ("annual", annual)):
            plan_id = f"{market.lower()}_{period}"
            plans.append({
                "plan_id": plan_id,
                "plan_name": f"Matchday+ {period.title()} ({market})",
                "market": market,
                "billing_period": period,
                "trial_days": 7 if period == "monthly" else 0,
            })
            if period == "monthly" and market in NEW_MONTHLY_PRICE:
                prices.append({"plan_id": plan_id, "currency": currency, "price": price,
                               "valid_from": START, "valid_to": PRICE_INCREASE_DATE - dt.timedelta(days=1)})
                prices.append({"plan_id": plan_id, "currency": currency, "price": NEW_MONTHLY_PRICE[market],
                               "valid_from": PRICE_INCREASE_DATE, "valid_to": None})
            else:
                prices.append({"plan_id": plan_id, "currency": currency, "price": price,
                               "valid_from": START, "valid_to": None})
    return pd.DataFrame(plans), pd.DataFrame(prices)


def build_fx(rng: np.random.Generator) -> pd.DataFrame:
    days = pd.date_range(START, END, freq="D")
    rows = []
    for currency, base in FX_START.items():
        if currency == "USD":
            path = np.ones(len(days))
        else:
            drift = {"COP": 0.00003, "CLP": 0.00002}.get(currency, 0.0)
            path = base * np.exp(np.cumsum(rng.normal(drift, 0.004, len(days))))
        rows.append(pd.DataFrame({"rate_date": days.date, "currency": currency, "units_per_usd": path.round(4)}))
    return pd.concat(rows, ignore_index=True)


def build_playback(access: list, rng: np.random.Generator) -> pd.DataFrame:
    frames = []
    big = np.array(sorted(BIG_MATCH_DAYS), dtype="datetime64[D]")
    for customer_id, start, end, engagement in access:
        days = np.arange(np.datetime64(start), np.datetime64(end) + 1, dtype="datetime64[D]")
        if len(days) == 0:
            continue
        weekday = (days.astype("int64") + 3) % 7  # 0 = Monday
        lam = 0.22 * engagement * np.where(weekday >= 5, 2.0, 1.0) * np.where(np.isin(days, big), 3.0, 1.0)
        n = rng.poisson(lam)
        if n.sum() == 0:
            continue
        played_day = np.repeat(days, n)
        frames.append(pd.DataFrame({"customer_id": customer_id, "played_day": played_day}))
    ev = pd.concat(frames, ignore_index=True)
    k = len(ev)
    content = rng.choice(["live", "vod", "highlight"], size=k, p=[0.45, 0.30, 0.25])
    mean_seconds = np.select([content == "live", content == "vod"], [3600, 1500], 180)
    watch = (rng.lognormal(0, 0.7, k) * mean_seconds * 0.6).round()
    played_at = ev["played_day"].to_numpy().astype("datetime64[s]") + rng.integers(0, 86_400, k).astype("timedelta64[s]")
    out = pd.DataFrame({
        "event_id": [f"e_{i:09d}" for i in range(1, k + 1)],
        "customer_id": ev["customer_id"],
        "event_type": "play_end",
        "content_type": content,
        "content_id": [f"{t[:1]}_{i:05d}" for t, i in zip(content, rng.integers(1, 4000, k))],
        "played_at": pd.Series(played_at).dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "watch_seconds": watch,
    })
    return out


def build_spend(customers: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    paid = customers[customers["acquisition_channel"].isin(PAID_CHANNEL_CAC_USD)].copy()
    paid["spend_date"] = pd.to_datetime(paid["created_at"]).dt.date
    g = paid.groupby(["spend_date", "country", "acquisition_channel"]).size().rename("signups").reset_index()
    cac = g["acquisition_channel"].map(PAID_CHANNEL_CAC_USD) * g["country"].map(MARKET_CAC_FACTOR)
    g["spend_usd"] = (g["signups"] * cac * rng.lognormal(0, 0.25, len(g))).round(2)
    return g.rename(columns={"country": "market", "acquisition_channel": "channel"})[
        ["spend_date", "market", "channel", "spend_usd"]]


# ------------------------------------------------------------------- quirks
def inject_quirks(customers: pd.DataFrame, playback: pd.DataFrame, payments: pd.DataFrame,
                  rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    customers = customers.drop(columns=["engagement", "big_match_signup"]).copy()
    customers["updated_at"] = customers["created_at"]

    # the CRM export repeats a row every time a profile changes
    dup = customers.sample(frac=0.08, random_state=int(rng.integers(1e9))).copy()
    dup["updated_at"] = dup["created_at"] + pd.to_timedelta(rng.integers(1, 400, len(dup)), unit="D")
    dup["updated_at"] = dup["updated_at"].clip(upper=pd.Timestamp(AS_OF) - pd.Timedelta(seconds=1))
    customers = pd.concat([customers, dup], ignore_index=True)

    messy = rng.random(len(customers))
    customers.loc[messy < 0.10, "country"] = customers.loc[messy < 0.10, "country"].str.lower()
    customers.loc[(messy >= 0.10) & (messy < 0.13), "country"] = " " + customers["country"] + " "
    no_channel = rng.random(len(customers)) < 0.04
    customers.loc[no_channel, "acquisition_channel"] = None

    store = payments["provider"].isin(["apple", "google"])
    payments.loc[store, "currency"] = payments.loc[store, "currency"].str.lower()

    dupes = playback.sample(frac=0.005, random_state=int(rng.integers(1e9)))
    playback = pd.concat([playback, dupes], ignore_index=True)
    bad = rng.random(len(playback)) < 0.001
    playback.loc[bad, "watch_seconds"] = np.where(rng.random(bad.sum()) < 0.5, -1.0, np.nan)
    return customers, playback, payments


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="data/raw", type=Path)
    parser.add_argument("--seed", default=42, type=int)
    parser.add_argument("--scale", default=1.0, type=float, help="multiplies daily signups")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sim = Simulator(args.seed, args.scale)
    sink = sim.run()
    rng = sim.rng

    customers = pd.DataFrame(sink.customers)
    subscriptions = pd.DataFrame(sink.subscriptions)
    payments = pd.DataFrame(sink.payments)
    playback = build_playback(sink.access, rng)
    spend = build_spend(customers, rng)
    plans, plan_prices = build_plans()
    fx = build_fx(rng)
    assignments = pd.DataFrame(sink.assignments)
    customers, playback, payments = inject_quirks(customers, playback, payments, rng)

    tables = {
        "crm_customers": customers,
        "billing_plans": plans,
        "billing_plan_prices": plan_prices,
        "billing_subscriptions": subscriptions,
        "billing_payments": payments,
        "finance_fx_rates": fx,
        "app_playback_events": playback,
        "marketing_spend": spend,
        "experiments_assignments": assignments,
    }
    for name, df in tables.items():
        df.to_parquet(args.out / f"{name}.parquet", index=False)
        print(f"{name:28s} {len(df):>10,d} rows")


if __name__ == "__main__":
    main()
