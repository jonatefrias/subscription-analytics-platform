"""The re-derivation gate: a number is reported only if a second, independent path agrees.

Independent paths, in order of preference
  1. MRR-bridge metrics  -> the hand-written mart finance.rpt_mrr_bridge (a different code path
                            from the metric definitions), aggregated to the requested grain with
                            the right rule: flows summed, closing snapshots from the last month,
                            opening snapshots from the first month.
  2. Other flow metrics  -> the same metric at a finer grain, summed (day -> month, month -> quarter/year).
  3. Other ratios        -> numerator and denominator queried separately, then divided.
Anything else is reported as unverifiable rather than guessed.
"""

import datetime as dt
import os
from typing import Any

import duckdb

from semantic_agent import metricflow as mf

GRAINS = {"month": 1, "quarter": 3, "year": 12}
FINER = {"month": "day", "quarter": "month", "year": "month"}
REL_TOL = 0.005  # 0.5 %: a reported value may be rounded

# metric -> (rpt_mrr_bridge column, how to aggregate months into the period)
BRIDGE = {
    "opening_mrr": ("opening_mrr_usd", "first"),
    "mrr": ("closing_mrr_usd", "last"),
    "paying_customers": ("closing_customers", "last"),
    "opening_customers_metric": ("opening_customers", "first"),
    "new_mrr": ("new_mrr_usd", "sum"),
    "reactivation_mrr": ("reactivation_mrr_usd", "sum"),
    "expansion_mrr": ("expansion_mrr_usd", "sum"),
    "contraction_mrr": ("contraction_mrr_usd", "sum"),
    "churned_mrr": ("churned_mrr_usd", "sum"),
    "churned_customers": ("churned_customers", "sum"),
}


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(0.01, REL_TOL * abs(b))


def _months(period_start: dt.date, grain: str) -> list[dt.date]:
    out, d = [], period_start
    for _ in range(GRAINS[grain]):
        out.append(d)
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def _semantic_value(metric: str, grain: str, period_start: str) -> float | None:
    column = f"metric_time__{grain}"
    rows = mf.query([metric], [column], where=f"{{{{ TimeDimension('metric_time', '{grain}') }}}} = '{period_start}'")
    return float(rows[0][metric]) if rows and rows[0][metric] not in ("", None) else None


def _bridge_rows(months: list[dt.date]) -> list[dict]:
    path = os.environ.get("DUCKDB_PATH", str(mf.ROOT / "data" / "warehouse.duckdb"))
    con = duckdb.connect(path, read_only=True)
    try:
        cur = con.execute(
            "select * from finance.rpt_mrr_bridge where month_start between ? and ? order by month_start",
            [months[0], months[-1]],
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    finally:
        con.close()


def _from_bridge(metric: str, months: list[dt.date]) -> float | None:
    rows = _bridge_rows(months)
    if len(rows) != len(months):
        return None
    if metric in BRIDGE:
        column, rule = BRIDGE[metric]
        values = [float(r[column]) for r in rows]
        return {"first": values[0], "last": values[-1], "sum": sum(values)}[rule]
    if metric == "net_new_mrr":
        return float(rows[-1]["closing_mrr_usd"]) - float(rows[0]["opening_mrr_usd"])
    if metric == "logo_churn_rate":
        opening = float(rows[0]["opening_customers"])
        return sum(float(r["churned_customers"]) for r in rows) / opening if opening else None
    if metric == "gross_mrr_churn_rate":
        opening = float(rows[0]["opening_mrr_usd"])
        lost = sum(float(r["churned_mrr_usd"]) + float(r["contraction_mrr_usd"]) for r in rows)
        return -lost / opening if opening else None
    if metric == "arpu":
        return float(rows[-1]["closing_mrr_usd"]) / float(rows[-1]["closing_customers"])
    return None


def _from_finer_grain(metric: str, grain: str, period_start: dt.date, months: list[dt.date]) -> float | None:
    finer = FINER[grain]
    end = dt.date(months[-1].year + (months[-1].month == 12), months[-1].month % 12 + 1, 1)
    rows = mf.query(
        [metric],
        [f"metric_time__{finer}"],
        where=(
            f"{{{{ TimeDimension('metric_time', '{finer}') }}}} >= '{period_start}' "
            f"and {{{{ TimeDimension('metric_time', '{finer}') }}}} < '{end}'"
        ),
    )
    return sum(float(r[metric] or 0) for r in rows)


def verify(metric: str, grain: str, period_start: str, reported_value: float) -> dict[str, Any]:
    if grain not in GRAINS:
        return {"status": "unverifiable", "reason": f"grain must be one of {sorted(GRAINS)}"}
    start = dt.date.fromisoformat(period_start)
    if start.day != 1 or (grain == "quarter" and start.month % 3 != 1) or (grain == "year" and start.month != 1):
        return {"status": "unverifiable", "reason": f"{period_start} is not the first day of a {grain}"}
    months = _months(start, grain)

    semantic = _semantic_value(metric, grain, period_start)
    definition = mf.metrics()[metric]
    independent, method = None, None
    if metric in BRIDGE or metric in ("net_new_mrr", "logo_churn_rate", "gross_mrr_churn_rate", "arpu"):
        independent, method = _from_bridge(metric, months), "hand-written mart finance.rpt_mrr_bridge"
    elif definition["type"] == "simple" and not mf.measures()[definition["type_params"]["measure"]["name"]][0].get(
        "non_additive_dimension"
    ):
        independent, method = _from_finer_grain(metric, grain, start, months), f"sum of daily/monthly {metric}"
    elif definition["type"] == "ratio":
        num = definition["type_params"]["numerator"]["name"]
        den = definition["type_params"]["denominator"]["name"]
        n, d = _semantic_value(num, grain, period_start), _semantic_value(den, grain, period_start)
        independent, method = (n / d if n is not None and d else None), f"{num} / {den} queried separately"

    result = {
        "metric": metric,
        "grain": grain,
        "period_start": period_start,
        "reported_value": reported_value,
        "semantic_layer_value": semantic,
        "independent_value": independent,
        "independent_method": method,
    }
    if independent is None or semantic is None:
        result["status"] = "unverifiable"
        result["reason"] = "no independent path for this metric" if method is None else "no data for that period"
    elif not _close(semantic, independent):
        result["status"] = "mismatch"
        result["reason"] = "the semantic layer and the independent path disagree; do not report this number"
    elif not _close(reported_value, semantic):
        result["status"] = "mismatch"
        result["reason"] = "the reported value differs from the data; re-read the query result"
    else:
        result["status"] = "confirmed"
    return result
