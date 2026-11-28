"""Reconcile the metrics Lightdash serves with the marts.

Lightdash translates the MetricFlow definitions into its own metrics on deploy. A translation is
code that can be wrong, and one feature does not carry over at all: snapshot (non-additive)
measures. This check queries the running Lightdash instance through its API and compares it with
the same mart the semantic-layer check uses.

Checks
  1. Monthly: every MRR-bridge metric served by Lightdash equals rpt_mrr_bridge.
  2. Guard: the MRR explore offers the month as its only time grain, because Lightdash would sum
     a snapshot across the months of a quarter.
  3. Native metric: the cohort retention rate equals fct_cohort_retention.

Needs the instance from `make lightdash`:  python scripts/check_lightdash.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.environ.get("DUCKDB_PATH", str(ROOT / "data" / "warehouse.duckdb"))
ENV_FILE = ROOT / "lightdash" / ".env"

PAIRS = {  # Lightdash metric -> rpt_mrr_bridge column
    "opening_mrr": "opening_mrr_usd",
    "new_mrr": "new_mrr_usd",
    "reactivation_mrr": "reactivation_mrr_usd",
    "expansion_mrr": "expansion_mrr_usd",
    "contraction_mrr": "contraction_mrr_usd",
    "churned_mrr": "churned_mrr_usd",
    "mrr": "closing_mrr_usd",
    "paying_customers": "closing_customers",
    "logo_churn_rate": "logo_churn_rate",
    "gross_mrr_churn_rate": None,  # churn plus contraction over opening MRR; derived below
    "arpu": "arpu_usd",
}


def settings() -> dict[str, str]:
    env = dict(os.environ)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            key, _, value = line.partition("=")
            env.setdefault(key, value)
    missing = [k for k in ("LIGHTDASH_URL", "LIGHTDASH_API_KEY", "LIGHTDASH_PROJECT") if k not in env]
    if missing:
        sys.exit(f"Missing {', '.join(missing)}. Start the instance with `make lightdash` first.")
    return env


def api(env: dict[str, str], method: str, path: str, body: dict | None = None):
    request = urllib.request.Request(
        f"{env['LIGHTDASH_URL']}/api/v1/projects/{env['LIGHTDASH_PROJECT']}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"ApiKey {env['LIGHTDASH_API_KEY']}", "content-type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())["results"]


def run_query(
    env: dict[str, str], explore: str, dimension: str, metrics: list[str]
) -> dict[str, dict[str, float | None]]:
    """Rows keyed by the dimension value, with raw metric values as floats."""
    body = {
        "exploreName": explore,
        "dimensions": [f"{explore}_{dimension}"],
        "metrics": [f"{explore}_{m}" for m in metrics],
        "filters": {},
        "sorts": [{"fieldId": f"{explore}_{dimension}", "descending": False}],
        "limit": 5000,
        "tableCalculations": [],
    }
    out = {}
    for row in api(env, "POST", f"/explores/{explore}/runQuery", body)["rows"]:
        key = str(row[f"{explore}_{dimension}"]["value"]["raw"])[:10]
        raw = {m: row[f"{explore}_{m}"]["value"]["raw"] for m in metrics}
        out[key] = {m: None if v is None else float(v) for m, v in raw.items()}
    return out


def close(a: float | None, b: float | None, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol * max(1.0, abs(b))


def main() -> int:
    env = settings()
    errors: list[str] = []
    con = duckdb.connect(DB_PATH, read_only=True)

    # 1. monthly bridge
    cur = con.execute("select * from finance.rpt_mrr_bridge order by month_start")
    cols = [d[0] for d in cur.description]
    bridge = {str(row[0])[:10]: dict(zip(cols, row, strict=True)) for row in cur.fetchall()}
    served = run_query(env, "fct_mrr_monthly", "month_start_month", list(PAIRS))
    if set(served) != set(bridge):
        errors.append(f"months differ: Lightdash has {len(served)}, rpt_mrr_bridge has {len(bridge)}")
    for month in sorted(set(served) & set(bridge)):
        for metric, column in PAIRS.items():
            mart = bridge[month]
            if column is None:
                lost = float(mart["churned_mrr_usd"] + mart["contraction_mrr_usd"])
                expected = -lost / float(mart["opening_mrr_usd"]) if mart["opening_mrr_usd"] else None
            else:
                expected = None if mart[column] is None else float(mart[column])
            if not close(served[month][metric], expected):
                errors.append(f"{month} {metric}: Lightdash {served[month][metric]} != mart {expected}")

    # 2. the snapshot guard
    explore = api(env, "GET", "/explores/fct_mrr_monthly")
    grains = sorted(
        d["timeInterval"]
        for d in explore["tables"]["fct_mrr_monthly"]["dimensions"].values()
        if d.get("timeIntervalBaseDimensionName") == "month_start"
    )
    if grains != ["MONTH"]:
        errors.append(f"fct_mrr_monthly.month_start offers {grains}; only MONTH is safe for snapshot metrics")

    # 3. the Lightdash-native retention metric
    retention = run_query(env, "fct_cohort_retention", "months_since_first_paid", ["cohort_retention_rate"])
    mart = con.execute("""
        select months_since_first_paid, sum(retained_customers) * 1.0 / sum(cohort_customers)
        from product.fct_cohort_retention group by 1
    """).fetchall()
    for months, expected in mart:
        got = retention.get(str(months), {}).get("cohort_retention_rate")
        if not close(got, expected):
            errors.append(f"retention at month {months}: Lightdash {got} != mart {expected}")

    if errors:
        print(f"Lightdash does not reconcile with the marts ({len(errors)} differences):")
        for line in errors[:20]:
            print("  " + line)
        return 1
    print(
        f"Lightdash reconciles: {len(served)} months x {len(PAIRS)} metrics, month-only grain on MRR, "
        f"{len(mart)} retention points."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
