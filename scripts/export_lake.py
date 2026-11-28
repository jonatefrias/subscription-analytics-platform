"""Publish the marts to a local DuckLake that Lightdash reads.

Lightdash connects to DuckDB through MotherDuck or DuckLake, not through a plain database file.
The project keeps building and testing in the DuckDB warehouse; this script copies the finished
marts into a DuckLake (a DuckDB catalog file plus Parquet data files) as the serving layer for BI.
Only marts are published: staging and intermediate models are not meant for exploration.

Usage:
    python scripts/export_lake.py --lake data/lake
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
MART_SCHEMAS = ("core", "finance", "product", "marketing", "experiments")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--warehouse", default=os.environ.get("DUCKDB_PATH", str(ROOT / "data" / "warehouse.duckdb")))
    parser.add_argument("--lake", type=Path, default=Path(os.environ.get("LAKE_DIR", ROOT / "data" / "lake")))
    args = parser.parse_args()

    lake = args.lake.resolve()
    shutil.rmtree(lake, ignore_errors=True)  # the lake is a derived copy: rebuild it from scratch
    (lake / "data").mkdir(parents=True)

    con = duckdb.connect()
    con.execute("install ducklake; load ducklake")
    con.execute(f"attach '{args.warehouse}' as warehouse (read_only)")
    con.execute(f"attach 'ducklake:{lake / 'catalog.duckdb'}' as ducklake (data_path '{lake / 'data'}')")

    tables = con.execute(
        """
        select table_schema, table_name
        from information_schema.tables
        where table_catalog = 'warehouse' and table_type = 'BASE TABLE' and table_schema in ?
        order by 1, 2
        """,
        [list(MART_SCHEMAS)],
    ).fetchall()
    for schema, table in tables:
        con.execute(f"create schema if not exists ducklake.{schema}")
        con.execute(f"create table ducklake.{schema}.{table} as select * from warehouse.{schema}.{table}")
        rows = con.execute(f"select count(*) from ducklake.{schema}.{table}").fetchone()[0]
        print(f"{schema + '.' + table:45s} {rows:>12,d} rows")
    con.close()
    print(f"\nDuckLake written to {lake}")


if __name__ == "__main__":
    main()
