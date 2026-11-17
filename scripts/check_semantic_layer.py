"""Reconcile the semantic layer with the marts.

The metric definitions in transform/models/semantic must return the same numbers as the
mart that finance already trusts (rpt_mrr_bridge). This catches a wrong filter, a wrong
aggregation or a snapshot measure that is accidentally summed over time.

Checks
  1. Monthly: every metric of the `mrr_bridge` saved query equals rpt_mrr_bridge.
  2. Quarterly: MRR at quarter grain equals the closing MRR of the quarter's last month,
     which proves the non-additive (snapshot) definition works.

Run from the repo root after `dbt build`:  python scripts/check_semantic_layer.py
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
TRANSFORM = ROOT / "transform"
DB_PATH = os.environ.get("DUCKDB_PATH", str(ROOT / "data" / "warehouse.duckdb"))

PAIRS = {  # saved-query metric -> rpt_mrr_bridge column
    "opening_mrr": "opening_mrr_usd",
    "new_mrr": "new_mrr_usd",
    "reactivation_mrr": "reactivation_mrr_usd",
    "expansion_mrr": "expansion_mrr_usd",
    "contraction_mrr": "contraction_mrr_usd",
    "churned_mrr": "churned_mrr_usd",
    "mrr": "closing_mrr_usd",
    "paying_customers": "closing_customers",
    "logo_churn_rate": "logo_churn_rate",
    "gross_mrr_churn_rate": None,  # no single mart column; checked below
    "arpu": "arpu_usd",
}


def mf(*args: str) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        out = tmp.name
    env = {**os.environ, "DBT_PROFILES_DIR": os.environ.get("DBT_PROFILES_DIR", ".")}
    subprocess.run(["mf", "query", *args, "--csv", out], cwd=TRANSFORM, env=env, check=True, stdout=subprocess.DEVNULL)
    with open(out, newline="") as f:
        return list(csv.DictReader(f))


def close(a: float | None, b: float | None, tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol * max(1.0, abs(b))


def num(v: str | None) -> float | None:
    return None if v in (None, "", "None") else float(v)


def main() -> int:
    errors: list[str] = []
    monthly = mf("--saved-query", "mrr_bridge")
    quarterly = mf("--metrics", "mrr", "--group-by", "metric_time__quarter")

    con = duckdb.connect(DB_PATH, read_only=True)
    cur = con.execute("select * from finance.rpt_mrr_bridge order by month_start")
    cols = [d[0] for d in cur.description]
    bridge = {str(row[0])[:10]: dict(zip(cols, row, strict=True)) for row in cur.fetchall()}

    for row in monthly:
        month = row["metric_time__month"][:10]
        mart = bridge.get(month)
        if mart is None:
            errors.append(f"{month}: in the semantic layer but not in rpt_mrr_bridge")
            continue
        for metric, column in PAIRS.items():
            value = num(row[metric])
            if column is None:
                expected = None
                if mart["opening_mrr_usd"]:
                    lost = float(mart["churned_mrr_usd"] + mart["contraction_mrr_usd"])
                    expected = -lost / float(mart["opening_mrr_usd"])
            else:
                expected = None if mart[column] is None else float(mart[column])
            if not close(value, expected, 1e-6):
                errors.append(f"{month} {metric}: semantic layer {value} vs mart {expected}")
    if len(monthly) != len(bridge):
        errors.append(f"month count differs: semantic layer {len(monthly)} vs mart {len(bridge)}")

    for row in quarterly:
        quarter_start = row["metric_time__quarter"][:10]
        months_in_quarter = sorted(m for m in bridge if quarter_start <= m < _next_quarter(quarter_start))
        expected = float(bridge[months_in_quarter[-1]]["closing_mrr_usd"])
        if not close(num(row["mrr"]), expected, 1e-6):
            errors.append(f"quarter {quarter_start}: MRR {row['mrr']} vs closing month {expected}")

    if errors:
        print(f"Semantic layer does NOT reconcile ({len(errors)} differences):")
        print("\n".join(f"  - {e}" for e in errors[:30]))
        return 1
    print(
        f"Semantic layer reconciles: {len(monthly)} months x {len(PAIRS)} metrics, "
        f"{len(quarterly)} quarters of snapshot MRR."
    )
    return 0


def _next_quarter(quarter_start: str) -> str:
    year, month = int(quarter_start[:4]), int(quarter_start[5:7])
    month += 3
    if month > 12:
        year, month = year + 1, month - 12
    return f"{year:04d}-{month:02d}-01"


if __name__ == "__main__":
    sys.exit(main())
