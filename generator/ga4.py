"""Web analytics events in the shape of the GA4 -> BigQuery export (`events_*` tables).

What is simulated on purpose:
  * one GA4 web stream; app signups (iOS, Android, TV) are not in it
  * anonymous visitors who never sign up (about 5 per web signup)
  * 0-3 research sessions before signup, sometimes on another device (another cookie)
  * the signup session funnel: landing -> view_paywall -> select_plan -> sign_up ->
    start_trial (monthly) or purchase (annual)
  * user_id is only sent after sign_up or login, so earlier sessions are anonymous
  * later login sessions, half of them on a new device, which link extra cookies to the customer
  * ~12% of web signups decline analytics consent and never reach GA4
  * the CRM channel is the first touch; later visits are often direct or paid-social retargeting,
    so last-touch models over-credit paid social

Export quirks (handled in dbt):
  * event_params is a repeated key/value record; every parameter must be unnested
  * event_timestamp is UTC microseconds, but event_date is the property's local date (New York)
  * traffic sources arrive with inconsistent spelling (facebook, fb, Meta, ig...) and mixed case
  * geo.country is a country name, not an ISO code
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pyarrow as pa

PROPERTY_TZ = "America/New_York"
COUNTRY_NAME = {"US": "United States", "MX": "Mexico", "ES": "Spain", "AR": "Argentina",
                "CL": "Chile", "CO": "Colombia", "PE": "Peru"}

# acquisition channel -> list of (source, medium, campaign) spellings seen in the wild
SOURCES = {
    "paid_social": [("facebook", "paid_social"), ("Facebook", "paid_social"), ("fb", "paid-social"),
                    ("instagram", "paid_social"), ("ig", "Paid_Social"), ("meta", "paid_social")],
    "paid_search": [("google", "cpc"), ("Google", "cpc"), ("bing", "cpc")],
    "organic": [("google", "organic"), ("bing", "organic"), (None, None)],
    "referral": [("refer-a-friend", "referral"), ("Refer-A-Friend", "referral")],
    "partner": [("telco_partner", "partner"), ("TelcoPartner", "partner")],
    "unknown": [(None, None)],
    "direct": [(None, None)],
}

PARAM_VALUE = pa.struct([("string_value", pa.string()), ("int_value", pa.int64()), ("double_value", pa.float64())])
SCHEMA = pa.schema([
    ("event_date", pa.string()),
    ("event_timestamp", pa.int64()),
    ("event_name", pa.string()),
    ("event_params", pa.list_(pa.struct([("key", pa.string()), ("value", PARAM_VALUE)]))),
    ("user_pseudo_id", pa.string()),
    ("user_id", pa.string()),
    ("platform", pa.string()),
    ("device", pa.struct([("category", pa.string()), ("operating_system", pa.string())])),
    ("geo", pa.struct([("country", pa.string())])),
    ("collected_traffic_source", pa.struct([("manual_source", pa.string()), ("manual_medium", pa.string()),
                                            ("manual_campaign_name", pa.string()), ("gclid", pa.string())])),
])


def _p(key: str, value) -> dict:
    if isinstance(value, str):
        return {"key": key, "value": {"string_value": value, "int_value": None, "double_value": None}}
    if isinstance(value, float):
        return {"key": key, "value": {"string_value": None, "int_value": None, "double_value": value}}
    return {"key": key, "value": {"string_value": None, "int_value": int(value), "double_value": None}}


class Ga4Builder:
    def __init__(self, rng: np.random.Generator, end_date: dt.date):
        self.rng = rng
        self.end = end_date
        self.rows: list[tuple] = []
        self.cookie_seq = 0

    def cookie(self) -> str:
        self.cookie_seq += 1
        return f"{int(self.rng.integers(10**8, 10**9))}.{1704067200 + self.cookie_seq}"

    def source_for(self, channel: str, market: str) -> dict:
        options = SOURCES[channel]
        source, medium = options[int(self.rng.integers(len(options)))]
        campaign = None
        gclid = None
        if channel in ("paid_social", "paid_search", "partner"):
            campaign = f"mdp_{market.lower()}_{self.rng.choice(['season', 'bigmatch', 'always_on'])}"
        if medium == "cpc" and source and source.lower() == "google":
            gclid = f"Cj0K{int(self.rng.integers(10**9))}"
        return {"manual_source": source, "manual_medium": medium, "manual_campaign_name": campaign, "gclid": gclid}

    def session(self, pseudo_id: str, start: dt.datetime, session_number: int, market: str,
                device: dict, traffic: dict, steps: list[tuple[str, list]], user_id: str | None = None,
                user_id_from_step: int | None = None) -> None:
        """Write one session. `steps` are (event_name, extra_params) after session_start."""
        session_id = int(start.timestamp())
        t = start
        events = [("session_start", [])] + steps
        for i, (name, extra) in enumerate(events):
            if i > 0:
                t += dt.timedelta(seconds=int(self.rng.integers(5, 180)))
            uid = user_id if (user_id_from_step is None or i >= user_id_from_step) else None
            params = [_p("ga_session_id", session_id), _p("ga_session_number", session_number)]
            if name in ("page_view", "view_paywall"):
                params.append(_p("engagement_time_msec", int(self.rng.integers(1_000, 90_000))))
            params += extra
            self.rows.append((
                t, name, params, pseudo_id, uid, device, {"country": COUNTRY_NAME[market]},
                traffic if i == 0 else None,
            ))

    @staticmethod
    def browse_steps(n_pages: int, paywall: bool) -> list[tuple[str, list]]:
        pages = ["/", "/live", "/schedule", "/pricing", "/highlights", "/teams"]
        steps = [("page_view", [_p("page_location", f"https://matchdayplus.example{pages[i % len(pages)]}")])
                 for i in range(n_pages)]
        if paywall:
            steps.append(("view_paywall", [_p("page_location", "https://matchdayplus.example/pricing")]))
        return steps

    # ---------------------------------------------------------------- customers
    def customer_journey(self, c: dict, first_sub: dict, price: float, currency: str) -> None:
        rng = self.rng
        if rng.random() < 0.12:  # declined analytics consent: GA4 never sees this person
            return
        market = c["country"]
        mobile = rng.random() < 0.55
        device = {"category": "mobile" if mobile else "desktop",
                  "operating_system": rng.choice(["iOS", "Android"]) if mobile else rng.choice(["Windows", "Macintosh"])}
        main_cookie = self.cookie()
        signup_at: dt.datetime = c["created_at"]
        channel = c["acquisition_channel"]

        n_pre = int(rng.choice(4, p=[0.40, 0.30, 0.20, 0.10]))
        offsets = sorted(rng.uniform(0.2, 14, n_pre), reverse=True)  # days before signup
        session_number = {main_cookie: 0}
        touch_channels = []
        for k, days_before in enumerate(offsets):
            cookie = main_cookie if rng.random() < 0.8 else self.cookie()
            session_number[cookie] = session_number.get(cookie, 0) + 1
            first = k == 0
            # later research visits: often direct, sometimes a paid-social retargeting ad
            ch = channel if first else rng.choice([channel, "direct", "organic", "paid_social"],
                                                  p=[0.20, 0.45, 0.15, 0.20])
            touch_channels.append(ch)
            self.session(cookie, signup_at - dt.timedelta(days=float(days_before)), session_number[cookie], market,
                         device, self.source_for(ch, market),
                         self.browse_steps(int(rng.integers(1, 4)), paywall=rng.random() < 0.5))

        # the signup session: first touch if there were no research sessions, otherwise mostly direct
        if n_pre == 0:
            ch = channel
        elif channel in ("paid_social", "paid_search"):
            ch = rng.choice([channel, "direct"], p=[0.5, 0.5])
        else:
            ch = rng.choice([channel, "direct"], p=[0.3, 0.7])
        session_number[main_cookie] += 1
        plan_id = first_sub["plan_id"]
        steps = self.browse_steps(int(rng.integers(1, 3)), paywall=True)
        steps.append(("select_plan", [_p("plan_id", plan_id)]))
        signup_step = len(steps) + 1  # +1 for session_start
        steps.append(("sign_up", [_p("method", rng.choice(["email", "google", "apple"]))]))
        if first_sub["trial_end_at"] is not None:
            steps.append(("start_trial", [_p("plan_id", plan_id), _p("transaction_id", first_sub["subscription_id"])]))
        else:
            steps.append(("purchase", [_p("plan_id", plan_id), _p("transaction_id", first_sub["subscription_id"]),
                                       _p("value", float(price)), _p("currency", currency)]))
        session_start = signup_at - dt.timedelta(seconds=int(rng.integers(60, 900)))
        self.session(main_cookie, session_start, session_number[main_cookie], market, device,
                     self.source_for(ch, market), steps, user_id=c["customer_id"], user_id_from_step=signup_step)

        # later logged-in sessions; half of them on a new device
        if rng.random() < 0.30:
            for _ in range(int(rng.integers(1, 4))):
                when = signup_at + dt.timedelta(days=float(rng.uniform(1, 90)))
                if when.date() > self.end:
                    break
                cookie = main_cookie if rng.random() < 0.5 else self.cookie()
                session_number[cookie] = session_number.get(cookie, 0) + 1
                self.session(cookie, when, session_number[cookie], market, device, self.source_for("direct", market),
                             [("login", [_p("method", "email")])] + self.browse_steps(int(rng.integers(1, 3)), False),
                             user_id=c["customer_id"])

    # ---------------------------------------------------------------- anonymous
    def anonymous_visitors(self, day: dt.date, n: int, market_weights: dict) -> None:
        rng = self.rng
        markets = list(market_weights)
        p = np.array([market_weights[m] for m in markets])
        channels = ["paid_social", "paid_search", "organic", "referral", "partner", "direct"]
        for _ in range(n):
            market = str(rng.choice(markets, p=p / p.sum()))
            ch = str(rng.choice(channels, p=[0.28, 0.18, 0.24, 0.04, 0.06, 0.20]))
            mobile = rng.random() < 0.6
            device = {"category": "mobile" if mobile else "desktop",
                      "operating_system": rng.choice(["iOS", "Android"]) if mobile else rng.choice(["Windows", "Macintosh"])}
            cookie = self.cookie()
            for s in range(1 + int(rng.random() < 0.3)):
                start = dt.datetime.combine(day, dt.time()) + dt.timedelta(
                    days=s * float(rng.uniform(0.5, 6)), seconds=int(rng.integers(0, 86_400)))
                if start.date() > self.end:
                    break
                steps = self.browse_steps(int(rng.integers(1, 4)), paywall=rng.random() < 0.25)
                if steps[-1][0] == "view_paywall" and rng.random() < 0.2:
                    steps.append(("select_plan", [_p("plan_id", f"{market.lower()}_monthly")]))
                self.session(cookie, start, s + 1, market, device,
                             self.source_for(ch if s == 0 else "direct", market), steps)

    def to_frame(self) -> pa.Table:
        df = pd.DataFrame(self.rows, columns=["event_at", "event_name", "event_params", "user_pseudo_id",
                                              "user_id", "device", "geo", "collected_traffic_source"])
        df = df[df["event_at"] < pd.Timestamp(self.end + dt.timedelta(days=1))].sort_values("event_at")
        utc = pd.to_datetime(df["event_at"]).dt.tz_localize("UTC")
        df["event_timestamp"] = utc.dt.as_unit("us").astype("int64")  # microseconds since epoch, as in the export
        df["event_date"] = utc.dt.tz_convert(PROPERTY_TZ).dt.strftime("%Y%m%d")
        df["platform"] = "WEB"
        df = df[[f.name for f in SCHEMA]]
        return pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)


def build_ga4_events(customers: pd.DataFrame, subscriptions: pd.DataFrame, plan_prices: pd.DataFrame,
                     markets: dict, end_date: dt.date, seed: int) -> pa.Table:
    """Uses its own random stream so adding GA4 does not change any other table."""
    builder = Ga4Builder(np.random.default_rng(seed + 1_000), end_date)
    first_sub = (subscriptions.sort_values("started_at").drop_duplicates("customer_id")
                 .set_index("customer_id").to_dict("index"))
    initial_price = plan_prices.sort_values("valid_from").drop_duplicates("plan_id").set_index("plan_id")

    web = customers[customers["signup_platform"] == "web"]
    for c in web.to_dict("records"):
        sub = first_sub[c["customer_id"]]
        trial = sub["trial_end_at"]
        sub["trial_end_at"] = None if trial is None or pd.isna(trial) else trial
        price_row = initial_price.loc[sub["plan_id"]]
        builder.customer_journey(c, sub, float(price_row["price"]), str(price_row["currency"]))

    weights = {m: v[1] for m, v in markets.items()}
    signups_per_day = web.groupby(pd.to_datetime(web["created_at"]).dt.date).size()
    for day, n in signups_per_day.items():
        builder.anonymous_visitors(day, int(builder.rng.poisson(5 * n)), weights)
    return builder.to_frame()
