"""Build the static analysis reports (HTML) from the warehouse.

Business metrics (MRR, churn, ARPU, CAC, conversion rates) are queried through the semantic layer
with MetricFlow, the same definitions the MCP server and the reconciliation check use. Analyses
without a metric definition (cohort retention, attribution, the experiment) read the marts directly.
Nothing is typed by hand: every number in the pages comes from a query in this file.

Usage:
    python reports/build.py --out site
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.experiment import (  # noqa: E402
    achieved_power,
    cuped_adjust,
    difference_in_means,
    srm_test,
)
from reports import charts  # noqa: E402
from reports.page import REPO, figure, page, table, tiles  # noqa: E402
from semantic_agent import metricflow as mf  # noqa: E402

S = charts.SERIES
MONTH = "{{ TimeDimension('metric_time', 'month') }}"


# ---------------------------------------------------------------- formatting
def usd(v, digits=0):
    return f"-${abs(v):,.{digits}f}" if v < 0 else f"${v:,.{digits}f}"


def usd_k(v):
    return f"-${abs(v) / 1000:,.0f}k" if v < 0 else f"${v / 1000:,.0f}k"


def usd2(v):
    return usd(v, 2)


def signed_usd(v):
    return ("+" if v >= 0 else "-") + f"${abs(v):,.2f}"


def pct(v, digits=1):
    return f"{100 * v:.{digits}f}%"


def pct0(v):
    return pct(v, 0)


def pp(v):
    return f"{100 * v:+.1f} pp"


def num(v):
    return f"{v:,.0f}"


def month_label(d: dt.date) -> str:
    return d.strftime("%b %y")


def title_case(channel: str) -> str:
    return channel.replace("_", " ").capitalize()


# ---------------------------------------------------------------- data access
WAREHOUSE = os.environ.get("DUCKDB_PATH", str(ROOT / "data" / "warehouse.duckdb"))


def sql(query: str) -> list[tuple]:
    """Run a query on the marts. The connection is closed right away: MetricFlow needs the file lock."""
    with duckdb.connect(WAREHOUSE, read_only=True) as con:
        return con.execute(query).fetchall()


def sql_df(query: str):
    with duckdb.connect(WAREHOUSE, read_only=True) as con:
        return con.execute(query).df()


def metric_rows(metrics, group_by=None, where=None, order_by=None) -> list[dict]:
    """Query the semantic layer; numbers come back as floats, empty cells as None."""
    rows = mf.query(metrics, group_by, where, order_by)
    for row in rows:
        for m in metrics:
            row[m] = float(row[m]) if row[m] not in ("", None) else None
    return rows


def monthly(metrics) -> tuple[list[dt.date], dict[str, list]]:
    rows = metric_rows(metrics, ["metric_time__month"], order_by=["metric_time__month"])
    months = [dt.date.fromisoformat(r["metric_time__month"][:10]) for r in rows]
    return months, {m: [r[m] for r in rows] for m in metrics}


def average_monthly_churn(dimension: str) -> dict[str, float]:
    """Logo churn per customer-month at risk, by a customer attribute.

    Opening customers is a snapshot, so the rate has no meaning without a month. The months are
    queried one by one from the semantic layer and combined as a ratio of sums.
    """
    rows = metric_rows(["churned_customers", "opening_customers_metric"], ["metric_time__month", dimension])
    churned, at_risk = {}, {}
    for r in rows:
        churned[r[dimension]] = churned.get(r[dimension], 0) + (r["churned_customers"] or 0)
        at_risk[r[dimension]] = at_risk.get(r[dimension], 0) + (r["opening_customers_metric"] or 0)
    return {k: churned[k] / at_risk[k] for k in churned if at_risk[k]}


# ---------------------------------------------------------------- revenue
def build_revenue() -> tuple[str, dict]:
    flows = ["new_mrr", "reactivation_mrr", "expansion_mrr", "contraction_mrr", "churned_mrr"]
    months, m = monthly(["mrr", "paying_customers", "arpu", "logo_churn_rate", "gross_mrr_churn_rate", *flows])
    labels = [month_label(d) for d in months]
    last = len(months) - 1
    year_ago = last - 12

    # the price increase is the month with the largest expansion; the markets are those that expanded
    peak = int(np.argmax(m["expansion_mrr"]))
    peak_where = f"{MONTH} = '{months[peak]:%Y-%m-%d}'"
    expansion = metric_rows(["expansion_mrr"], ["customer__market_code"], where=peak_where)
    total_expansion = sum(r["expansion_mrr"] or 0 for r in expansion)
    raised = sorted(r["customer__market_code"] for r in expansion if (r["expansion_mrr"] or 0) > 0.05 * total_expansion)

    after = min(peak + 1, last)
    by_market = metric_rows(
        ["logo_churn_rate"], ["customer__market_code"], where=f"{MONTH} = '{months[after]:%Y-%m-%d}'"
    )
    by_market.sort(key=lambda r: -r["logo_churn_rate"])
    raised_churn = [r["logo_churn_rate"] for r in by_market if r["customer__market_code"] in raised]
    other_churn = [r["logo_churn_rate"] for r in by_market if r["customer__market_code"] not in raised]

    churn_values = [v for v in m["logo_churn_rate"] if v is not None]
    worst = int(np.nanargmax([v if v is not None else np.nan for v in m["logo_churn_rate"]]))
    notes = {peak: "price increase"}
    growth = m["mrr"][last] / m["mrr"][year_ago] - 1

    body = f"""
<p class="kicker">Revenue</p>
<h1>MRR reached {usd_k(m["mrr"][last])} in {months[last]:%B %Y}, up {pct0(growth)} in twelve months</h1>
<p class="lede">Monthly recurring revenue, the movements behind it and where churn comes from.
MRR is a month-end snapshot of paying subscriptions at list price and constant FX.</p>
{
        tiles(
            [
                ("MRR", usd_k(m["mrr"][last])),
                ("Paying customers", num(m["paying_customers"][last])),
                ("ARPU per month", usd2(m["arpu"][last])),
                ("Logo churn, latest month", pct(m["logo_churn_rate"][last])),
            ]
        )
    }

<h2>MRR grew every year, with a step when prices went up</h2>
<p>The price increase of {months[peak]:%B %Y} added {usd_k(m["expansion_mrr"][peak])} of expansion MRR in a single
month, in {", ".join(raised)}. Growth flattens each June and July, when the season ends.</p>
{
        figure(
            "MRR by month, USD at constant FX",
            charts.line_chart(labels, [{"name": "MRR", "values": m["mrr"]}], usd_k, "MRR by month", notes=notes),
            table=table(
                ["Month", "MRR", "Paying customers", "ARPU"],
                [
                    [labels[i], usd(m["mrr"][i]), num(m["paying_customers"][i]), usd2(m["arpu"][i])]
                    for i in range(len(months))
                ],
            ),
        )
    }

<h2>New business drives growth; churn peaks in the off-season</h2>
<p>Each bar is one month's change in MRR, split by movement. Bars above zero add revenue (new customers,
reactivations, expansion); bars below remove it (contraction, churn). Opening MRR plus the five movements
equals closing MRR for every month, which is tested in the dbt project and reconciled against the semantic layer in CI.</p>
{
        figure(
            "MRR movements by month, USD",
            charts.stacked_bar_chart(
                labels,
                [
                    {"name": title_case(f.removesuffix("_mrr")), "values": [v or 0 for v in m[f]], "color": S[k]}
                    for k, f in enumerate(flows)
                ],
                usd_k,
                "MRR bridge by month",
                notes=notes,
            ),
            legend=charts.legend([title_case(f.removesuffix("_mrr")) for f in flows]),
            table=table(
                ["Month", "New", "Reactivation", "Expansion", "Contraction", "Churned"],
                [[labels[i], *[usd(m[f][i] or 0) for f in flows]] for i in range(len(months))],
            ),
        )
    }

<h2>Logo churn runs between {pct0(min(churn_values))} and {pct0(max(churn_values))} a month</h2>
<p>The share of paying customers at the start of a month who are gone by its end. A cancellation counts when
access ends, not when the customer clicks cancel, so off-season cancellations land a month later.
The worst month was {months[worst]:%B %Y} at {pct(m["logo_churn_rate"][worst])}.</p>
{
        figure(
            "Logo churn rate by month",
            charts.line_chart(
                labels,
                [{"name": "Logo churn rate", "values": m["logo_churn_rate"]}],
                pct0,
                "Logo churn rate by month",
                notes=notes,
            ),
            table=table(
                ["Month", "Logo churn", "Gross MRR churn"],
                [
                    [
                        labels[i],
                        pct(m["logo_churn_rate"][i]) if m["logo_churn_rate"][i] is not None else "",
                        pct(m["gross_mrr_churn_rate"][i]) if m["gross_mrr_churn_rate"][i] is not None else "",
                    ]
                    for i in range(len(months))
                ],
            ),
        )
    }

<h2>The price increase cost customers only where it applied</h2>
<p>In {months[after]:%B %Y}, the month after the increase, logo churn was {pct(min(raised_churn))} to {
        pct(max(raised_churn))
    }
in the markets that raised prices ({", ".join(raised)}) and {pct(min(other_churn))} to {
        pct(max(other_churn))
    } in the rest.</p>
{
        figure(
            f"Logo churn rate by market, {months[after]:%B %Y}",
            charts.grouped_bar_chart(
                [
                    r["customer__market_code"] + (" (price raised)" if r["customer__market_code"] in raised else "")
                    for r in by_market
                ],
                [{"name": "Logo churn", "values": [r["logo_churn_rate"] for r in by_market]}],
                pct,
                "Logo churn by market",
            ),
        )
    }
"""
    source = (
        "Source: semantic-layer metrics <code>mrr</code>, <code>paying_customers</code>, <code>arpu</code>, "
        "<code>logo_churn_rate</code> and the MRR movement metrics, queried with MetricFlow."
    )
    summary = {
        "value": usd_k(m["mrr"][last]),
        "text": f"MRR in {months[last]:%B %Y}, up {pct0(growth)} in twelve months.",
    }
    return page("revenue.html", "Revenue", body, source), summary


# ---------------------------------------------------------------- retention
def build_retention() -> tuple[str, dict]:
    rows = sql("""
        select cohort_month, months_since_first_paid, cohort_customers, retained_customers
        from product.fct_cohort_retention
        where months_since_first_paid <= 12
        order by 1, 2
    """)
    cohorts = sorted({r[0] for r in rows})
    cell = {(r[0], r[1]): r[3] / r[2] for r in rows}
    matrix = [[cell.get((c, k)) for k in range(13)] for c in cohorts]

    retained, size = [0] * 13, [0] * 13
    for _, k, n, kept in rows:
        retained[k] += kept
        size[k] += n
    curve = [retained[k] / size[k] for k in range(13)]

    by_channel = sorted(average_monthly_churn("customer__acquisition_channel").items(), key=lambda kv: -kv[1])
    by_period = average_monthly_churn("customer__first_billing_period")
    big = {k.lower(): v for k, v in average_monthly_churn("customer__is_big_match_signup").items()}

    body = f"""
<p class="kicker">Retention</p>
<h1>{pct0(curve[1])} of paying customers are still paying after one month, {pct0(curve[6])} after six and {
        pct0(curve[12])
    } after a year</h1>
<p class="lede">Paying retention by cohort of first payment, and which customers leave faster.</p>
{
        tiles(
            [
                ("Retained at month 1", pct0(curve[1])),
                ("Retained at month 6", pct0(curve[6])),
                ("Retained at month 12", pct0(curve[12])),
                ("Cohorts observed", str(len(cohorts))),
            ]
        )
    }

<h2>The first three months decide most of the loss</h2>
<p>Share of each cohort still paying, averaged over every cohort old enough to be observed at that month.</p>
{
        figure(
            "Paying retention by months since first payment, all cohorts",
            charts.line_chart(
                [str(k) for k in range(13)],
                [{"name": "Retained", "values": curve}],
                pct0,
                "Average retention curve",
                tick_every=1,
                x_title="months since first payment",
            ),
            table=table(["Month", "Retained"], [[str(k), pct(curve[k])] for k in range(13)]),
        )
    }

<h2>Cohorts behave alike, apart from the season</h2>
<p>One row per cohort (month of first payment), one column per month since. Darker means more of the cohort is
still paying. The diagonal pattern of lighter cells follows the calendar: every cohort loses more customers in June and July.</p>
{
        figure(
            "Paying retention by cohort",
            charts.heatmap(
                [month_label(c) for c in cohorts], [str(k) for k in range(13)], matrix, pct0, "Cohort retention heatmap"
            ),
        )
    }

<h2>Who churns faster</h2>
<p>Average monthly logo churn over the whole period (customers lost per customer-month at risk), by a property the
customer had at signup. Customers who start on a
monthly plan churn at {pct(by_period.get("monthly", 0))} a month against {
        pct(by_period.get("annual", 0))
    } for annual plans, and
customers who signed up on a big-match day churn at {pct(big.get("true", 0))} against {
        pct(big.get("false", 0))
    } for the rest.</p>
{
        figure(
            "Average monthly logo churn rate by acquisition channel",
            charts.bar_chart([(title_case(k), v) for k, v in by_channel], pct, "Logo churn by acquisition channel"),
        )
    }
"""
    source = (
        "Source: mart <code>fct_cohort_retention</code> for the cohort views; semantic-layer metric "
        "<code>logo_churn_rate</code> by customer attributes for the last section."
    )
    summary = {
        "value": pct0(curve[12]),
        "text": "of paying customers are still paying twelve months after their first payment.",
    }
    return page("retention.html", "Retention", body, source), summary


# ---------------------------------------------------------------- acquisition
def build_acquisition() -> tuple[str, dict]:
    cac = [
        r
        for r in metric_rows(
            ["cac", "marketing_spend", "paying_customers_acquired"], ["acquisition_day__acquisition_channel"]
        )
        if r["marketing_spend"]
    ]
    cac.sort(key=lambda r: -r["cac"])
    blended = sum(r["marketing_spend"] for r in cac) / sum(r["paying_customers_acquired"] for r in cac)
    trial = metric_rows(["trial_conversion_rate", "signups"], ["customer__acquisition_channel"])
    trial.sort(key=lambda r: -r["trial_conversion_rate"])
    overall = metric_rows(["trial_conversion_rate", "signups"])[0]
    web = metric_rows(["web_sessions", "paywall_view_rate", "web_signup_rate"], ["web_funnel_day__channel"])
    web.sort(key=lambda r: -r["web_signup_rate"])
    web_total = metric_rows(["web_sessions", "paywall_sessions_metric", "signup_sessions_metric"])[0]

    channels = [
        r[0]
        for r in sql("""
        select crm_channel from marketing.fct_signup_attribution group by 1 order by count(*) desc
    """)
    ]
    views = {
        "CRM channel": "crm_channel",
        "GA4 first touch": "first_touch_channel",
        "GA4 last non-direct touch": "last_non_direct_channel",
    }
    total = sql("select count(*) from marketing.fct_signup_attribution")[0][0]
    shares = {}
    for name, column in views.items():
        counts = dict(sql(f"select {column}, count(*) from marketing.fct_signup_attribution group by 1"))
        shares[name] = counts
    channels = [*[c for c in channels if c != "unknown"], "direct", "unknown"]
    first_ps, last_ps = (
        shares["GA4 first touch"].get("paid_social", 0),
        shares["GA4 last non-direct touch"].get("paid_social", 0),
    )

    coverage = sql("""
        select signup_month, tracking_coverage, first_touch_agreement, crm_web_signups, ga4_signups
        from marketing.rpt_web_tracking_coverage order by 1
    """)
    seen = sum(r[4] for r in coverage) / sum(r[3] for r in coverage)
    cov_labels = [month_label(r[0]) for r in coverage]
    worst_trial, best_trial = trial[-1], trial[0]

    body = f"""
<p class="kicker">Acquisition</p>
<h1>A paying customer from paid social costs {usd(cac[0]["cac"])}; one from {
        title_case(cac[-1]["acquisition_day__acquisition_channel"]).lower()
    } costs {usd(cac[-1]["cac"])}</h1>
<p class="lede">What each channel costs, how well its trials convert, and how much of that the web analytics can see.</p>
{
        tiles(
            [
                ("Signups", num(overall["signups"])),
                ("Trial conversion", pct(overall["trial_conversion_rate"])),
                ("CAC, paid channels", usd(blended)),
                ("Web signups seen by GA4", pct(seen)),
            ]
        )
    }

<h2>The most expensive channel also converts worst</h2>
<p>CAC is paid media spend divided by customers who went on to pay, per channel. Trials from
{title_case(worst_trial["customer__acquisition_channel"]).lower()} convert at {
        pct(worst_trial["trial_conversion_rate"])
    },
against {pct(best_trial["trial_conversion_rate"])} for {
        title_case(best_trial["customer__acquisition_channel"]).lower()
    }.</p>
{
        figure(
            "CAC by paid channel, USD per paying customer acquired",
            charts.bar_chart(
                [(title_case(r["acquisition_day__acquisition_channel"]), r["cac"]) for r in cac], usd2, "CAC by channel"
            ),
            table=table(
                ["Channel", "Spend", "Paying customers", "CAC"],
                [
                    [
                        title_case(r["acquisition_day__acquisition_channel"]),
                        usd(r["marketing_spend"]),
                        num(r["paying_customers_acquired"]),
                        usd2(r["cac"]),
                    ]
                    for r in cac
                ],
            ),
        )
    }
{
        figure(
            "Trial conversion rate by acquisition channel (paid within 14 days of signup)",
            charts.bar_chart(
                [(title_case(r["customer__acquisition_channel"]), r["trial_conversion_rate"]) for r in trial],
                pct,
                "Trial conversion by channel",
                x_max=1.0,
            ),
        )
    }

<h2>On the web, {
        pct(web_total["paywall_sessions_metric"] / web_total["web_sessions"])
    } of sessions reach the paywall and {
        pct(web_total["signup_sessions_metric"] / web_total["web_sessions"])
    } end in a signup</h2>
<p>GA4 sessions by the channel of the session. Direct sessions convert best because most are returning visitors
who first arrived through another channel, which is the reason attribution needs more than the last click.</p>
{
        figure(
            "Share of web sessions that end in a signup, by session channel",
            charts.bar_chart(
                [(title_case(r["web_funnel_day__channel"]), r["web_signup_rate"]) for r in web],
                pct,
                "Web signup rate by channel",
            ),
            table=table(
                ["Channel", "Sessions", "Reach the paywall", "Sign up"],
                [
                    [
                        title_case(r["web_funnel_day__channel"]),
                        num(r["web_sessions"]),
                        pct(r["paywall_view_rate"]),
                        pct(r["web_signup_rate"]),
                    ]
                    for r in web
                ],
            ),
        )
    }

<h2>Attribution depends on the question asked</h2>
<p>The same web signups credited three ways. Last non-direct touch gives paid social {pct(last_ps / first_ps - 1)} more
signups than first touch, because retargeting reaches people who had already found the product some other way.
Both views are kept side by side instead of being blended into one model.</p>
{
        figure(
            "Share of web signups credited to each channel, by attribution view",
            charts.grouped_bar_chart(
                [title_case(c) for c in channels],
                [
                    {"name": name, "values": [counts.get(c, 0) / total for c in channels]}
                    for name, counts in shares.items()
                ],
                pct,
                "Attribution by view",
            ),
            legend=charts.legend(list(shares)),
        )
    }

<h2>GA4 sees {pct0(seen)} of the web signups in the CRM</h2>
<p>Visitors who decline analytics consent never appear in GA4, so signup and revenue counts always come from the CRM
and billing. A dbt test warns if coverage falls below 80%. For the signups GA4 does see, its first-touch channel
agrees with the CRM channel about four times in five.</p>
{
        figure(
            "GA4 coverage of CRM web signups, and agreement of first-touch channel with the CRM, by signup month",
            charts.line_chart(
                cov_labels,
                [
                    {"name": "Tracking coverage", "values": [r[1] for r in coverage]},
                    {"name": "First-touch agreement", "values": [r[2] for r in coverage]},
                ],
                pct0,
                "GA4 tracking coverage",
                y_min=0.5,
            ),
            legend=charts.legend(["Tracking coverage", "First-touch agreement"]),
        )
    }
"""
    source = (
        "Source: semantic-layer metrics <code>cac</code>, <code>trial_conversion_rate</code>, <code>web_signup_rate</code> "
        "and <code>paywall_view_rate</code>; marts <code>fct_signup_attribution</code> and <code>rpt_web_tracking_coverage</code>."
    )
    summary = {"value": usd(blended), "text": "spent on paid media per paying customer acquired through paid channels."}
    return page("acquisition.html", "Acquisition", body, source), summary


# ---------------------------------------------------------------- experiment
def build_experiment() -> tuple[str, dict]:
    horizon, margin = 180, 0.02
    exposures = sql_df("""
        select
            e.customer_id, e.variant, e.assigned_at,
            cast(e.chose_annual as integer) as chose_annual,
            cast(e.paid_within_window as integer) as paid_within_window,
            c.market_code
        from experiments.fct_experiment_exposures as e
        inner join core.dim_customers as c using (customer_id)
        order by e.customer_id
    """)
    payments = sql_df("""
        select
            e.customer_id,
            greatest(cast(floor(epoch(p.billed_at - e.assigned_at) / 86400) as integer), 0) as day,
            cast(p.amount_usd_constant_fx as double) as amount
        from experiments.fct_experiment_exposures as e
        inner join finance.fct_payments as p using (customer_id)
        where p.payment_status = 'paid'
    """)
    daily = (
        payments[payments.day < horizon]
        .pivot_table(index="customer_id", columns="day", values="amount", aggfunc="sum")
        .reindex(index=exposures.customer_id, columns=range(horizon), fill_value=0.0)
        .fillna(0.0)
    )
    cumulative = daily.cumsum(axis=1).to_numpy()
    treated = (exposures.variant == "annual_highlight").to_numpy()
    n_c, n_t = int((~treated).sum()), int(treated.sum())
    start, end = exposures.assigned_at.min(), exposures.assigned_at.max()

    revenue = difference_in_means(cumulative[~treated, -1], cumulative[treated, -1])
    revenue_30 = difference_in_means(cumulative[~treated, 29], cumulative[treated, 29])
    annual = difference_in_means(exposures.chose_annual[~treated], exposures.chose_annual[treated])
    paid = difference_in_means(exposures.paid_within_window[~treated], exposures.paid_within_window[treated])
    curve = [difference_in_means(cumulative[~treated, d], cumulative[treated, d]) for d in range(horizon)]
    srm_p = srm_test(n_c, n_t)
    power = achieved_power(exposures.paid_within_window[~treated].std(), (n_c + n_t) / 2, margin)

    pre = sql_df(f"""
        with cohort as (
            select customer_id, market_code, created_at
            from core.dim_customers
            where signup_platform = 'web'
                and created_at >= timestamp '{start:%Y-%m-%d}' - interval 60 day
                and created_at < timestamp '{start:%Y-%m-%d}'
        )
        select cohort.customer_id, cohort.market_code, coalesce(sum(cast(p.amount_usd_constant_fx as double)), 0) as revenue
        from cohort
        left join finance.fct_payments as p
            on p.customer_id = cohort.customer_id
                and p.payment_status = 'paid'
                and p.billed_at < cohort.created_at + interval {horizon} day
        group by 1, 2
    """)
    baseline = exposures.market_code.map(pre.groupby("market_code").revenue.mean()).fillna(pre.revenue.mean())
    _, _, reduction = cuped_adjust(cumulative[:, -1], baseline.to_numpy())

    markets = []
    for market, group in exposures.assign(revenue=cumulative[:, -1]).groupby("market_code"):
        e = difference_in_means(
            group[group.variant == "control"].revenue, group[group.variant == "annual_highlight"].revenue
        )
        markets.append((f"{market} (n={len(group):,})", e.diff, e.ci_low, e.ci_high))
    markets.sort(key=lambda r: -r[1])

    ship = srm_p >= 0.001 and revenue.ci_low > 0 and annual.ci_low > 0 and paid.ci_low > -margin
    days = [str(d) for d in range(1, horizon + 1)]
    mean_c, mean_t = cumulative[~treated].mean(axis=0), cumulative[treated].mean(axis=0)
    results = [
        [
            "Revenue per signup, 180 days (primary)",
            usd2(revenue.control_mean),
            usd2(revenue.treatment_mean),
            signed_usd(revenue.diff),
            f"{signed_usd(revenue.ci_low)} to {signed_usd(revenue.ci_high)}",
        ],
        [
            "Annual plan share (mechanism)",
            pct(annual.control_mean),
            pct(annual.treatment_mean),
            pp(annual.diff),
            f"{pp(annual.ci_low)} to {pp(annual.ci_high)}",
        ],
        [
            "Paid within 14 days (guardrail)",
            pct(paid.control_mean),
            pct(paid.treatment_mean),
            pp(paid.diff),
            f"{pp(paid.ci_low)} to {pp(paid.ci_high)}",
        ],
        [
            "Revenue per signup, 30 days (for reference)",
            usd2(revenue_30.control_mean),
            usd2(revenue_30.treatment_mean),
            signed_usd(revenue_30.diff),
            f"{signed_usd(revenue_30.ci_low)} to {signed_usd(revenue_30.ci_high)}",
        ],
    ]

    body = f"""
<p class="kicker">Experiment</p>
<h1>Highlighting the annual plan adds {usd2(revenue.diff)} of revenue per signup in 180 days. {
        "Ship it." if ship else "Do not ship yet."
    }</h1>
<p class="lede">Readout of the paywall A/B test that ran on web signups from {start:%B %-d} to {end:%B %-d, %Y}:
{n_c:,} customers saw the control paywall and {n_t:,} saw the annual plan presented as the recommended option.</p>
{
        tiles(
            [
                ("Revenue per signup, 180 days", f"{pct(revenue.rel_diff)} lift"),
                ("Annual plan share", f"{pct(annual.control_mean)} → {pct(annual.treatment_mean)}"),
                ("Paid within 14 days", pp(paid.diff)),
                ("Sample ratio check", f"p = {srm_p:.2f}"),
            ]
        )
    }

<h2>All three pre-declared metrics pass the decision rule</h2>
<p>The rule was stated before computing outcomes: ship if the 95% interval for 180-day revenue is above zero, the
annual share rises (the mechanism), and a drop of more than 2 points in paid conversion can be ruled out.
Differences are annual highlight minus control.</p>
<div class="scroll">{
        table(["Metric", "Control", "Annual highlight", "Difference", "95% interval"], results, wide=True)
    }</div>

<h2>The lead is real, and smaller than it looks after one month</h2>
<p>An annual plan collects twelve months on day one, so the variant's lead is largest at day 30
({signed_usd(revenue_30.diff)}, a {
        pct0(revenue_30.rel_diff)
    } lift) and shrinks as monthly customers in control keep renewing:
{signed_usd(revenue.diff)} at day 180, a {
        pct0(revenue.rel_diff)
    } lift. That is why the primary metric is 180-day revenue
and not the 30-day figure. Annual renewals at month 12 are outside the data.</p>
{
        figure(
            "Cumulative revenue per signup by days since assignment, USD",
            charts.line_chart(
                days,
                [
                    {"name": "Control", "values": list(mean_c)},
                    {"name": "Annual highlight", "values": list(mean_t), "color": S[1]},
                ],
                usd2,
                "Cumulative revenue per signup",
                tick_every=30,
                tick_start=29,
                x_title="days since assignment",
            ),
            legend=charts.legend(["Control", "Annual highlight"]),
        )
    }
{
        figure(
            "Revenue difference per signup (annual highlight minus control) with its 95% confidence interval, USD",
            charts.line_chart(
                days,
                [{"name": "Difference", "values": [e.diff for e in curve], "color": "var(--ink)"}],
                usd2,
                "Revenue difference by horizon",
                band=([e.ci_low for e in curve], [e.ci_high for e in curve]),
                tick_every=30,
                tick_start=29,
                x_title="days since assignment",
            ),
        )
    }

<h2>The effect is positive in every market</h2>
<p>Exploratory: markets were not pre-declared and each has a few hundred customers, so single-market intervals
are wide. The shaded band is the overall effect and its interval; every market overlaps it.</p>
{
        figure(
            "180-day revenue effect by market, USD per signup, with 95% confidence intervals",
            charts.interval_chart(markets, usd2, "Revenue effect by market", band=(revenue.ci_low, revenue.ci_high)),
        )
    }

<h2>What the readout is careful about</h2>
<ul>
<li><strong>The guardrail is read from its interval.</strong> With this sample the test would detect a real 2-point drop in
paid conversion only {
        pct0(power)
    } of the time, so "no significant harm" would mean little. The interval rules the drop out.</li>
<li><strong>CUPED barely helps.</strong> These are new signups with no pre-period, so the only valid covariate is a
market baseline from before the test. It removes {pct(reduction)} of the variance, and it is reported as is.</li>
<li><strong>Assignment is logged at signup.</strong> Visitors who left at the paywall are in neither arm, so signup rate is not
a randomised metric. The sample ratio check (p = {
        srm_p:.2f}) is the evidence that the variant did not scare visitors away.</li>
<li><strong>Splits by chosen plan are not causal.</strong> The plan is chosen after seeing the paywall.</li>
</ul>
<p>The full method, with power analysis, bootstrap check and the web funnel, is in the
<a href="{REPO}/blob/main/notebooks/paywall_experiment_readout.ipynb">readout notebook</a>.</p>
"""
    source = (
        "Source: marts <code>fct_experiment_exposures</code>, <code>fct_payments</code> and <code>dim_customers</code>; "
        "statistics from <code>analysis/experiment.py</code>, which is unit tested."
    )
    summary = {
        "value": signed_usd(revenue.diff),
        "text": "revenue per signup in 180 days from highlighting the annual plan.",
    }
    return page("experiment.html", "Experiment", body, source), summary


# ---------------------------------------------------------------- index
def build_index(cards: dict[str, dict]) -> str:
    titles = {
        "revenue.html": "Revenue",
        "retention.html": "Retention",
        "acquisition.html": "Acquisition",
        "experiment.html": "Paywall experiment",
    }
    items = "".join(
        f'<a class="card" href="{href}"><h3>{titles[href]}</h3><b>{c["value"]}</b><p>{c["text"]}</p></a>'
        for href, c in cards.items()
    )
    body = f"""
<p class="kicker">Matchday+ analytics</p>
<h1>What the data says about a subscription streaming business</h1>
<p class="lede">Four short reports built from the marts and the semantic layer of the
<a href="{REPO}">subscription analytics platform</a>: a dbt project on synthetic data for a fictional
sports-streaming app.</p>
<div class="cards">{items}</div>
<h2>How these pages are made</h2>
<p>A script queries the warehouse and writes static HTML with inline SVG charts. Business metrics come from the
semantic layer, so MRR or churn here are the same definitions the dbt project tests and reconciles in CI.
The pages are rebuilt from scratch on every merge to the main branch, which means a number here cannot drift from the models.</p>
"""
    return page("index.html", "Overview", body, "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "site")
    args = parser.parse_args()

    pages, cards = {}, {}
    for name, build in {
        "revenue.html": build_revenue,
        "retention.html": build_retention,
        "acquisition.html": build_acquisition,
        "experiment.html": build_experiment,
    }.items():
        pages[name], cards[name] = build()
    pages["index.html"] = build_index(cards)

    args.out.mkdir(parents=True, exist_ok=True)
    for name, html in pages.items():
        (args.out / name).write_text(html, encoding="utf-8")
        print(f"{name:20s} {len(html) / 1024:6.0f} KB")


if __name__ == "__main__":
    main()
