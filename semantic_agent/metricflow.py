"""Thin, read-only wrapper around the MetricFlow CLI and the semantic manifest.

The CLI is the stable public interface of MetricFlow, so the server shells out to it rather
than importing internals. Every call runs in transform/ with the project's dbt profile.
"""

import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[1]))
TRANSFORM = ROOT / "transform"
SEMANTIC_MANIFEST = TRANSFORM / "target" / "semantic_manifest.json"
MF = str(Path(sys.executable).with_name("mf"))
DBT = str(Path(sys.executable).with_name("dbt"))
NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class QueryError(ToolError):
    """A query MetricFlow rejected or a metric that does not exist. ToolError sends the message
    to the client (other exceptions are masked), so the analyst can correct the call."""


def _env() -> dict:
    return {**os.environ, "DBT_PROFILES_DIR": os.environ.get("DBT_PROFILES_DIR", str(TRANSFORM))}


def _run(args: list[str]) -> str:
    result = subprocess.run(args, cwd=TRANSFORM, env=_env(), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        lines = [ln for ln in (result.stdout + result.stderr).splitlines() if ln.strip() and "pip install" not in ln]
        raise QueryError("\n".join(lines[-15:]))
    return result.stdout


@lru_cache(maxsize=1)
def manifest() -> dict:
    if not SEMANTIC_MANIFEST.exists():
        _run([DBT, "--quiet", "parse"])
    return json.loads(SEMANTIC_MANIFEST.read_text())


def metrics() -> dict[str, dict]:
    return {m["name"]: m for m in manifest()["metrics"]}


def measures() -> dict[str, tuple[dict, dict]]:
    """measure name -> (measure, semantic model)."""
    found = {}
    for sm in manifest()["semantic_models"]:
        for measure in sm["measures"]:
            found[measure["name"]] = (measure, sm)
    return found


def check_metric_names(names: list[str]) -> None:
    known = metrics()
    unknown = [n for n in names if n not in known]
    if unknown:
        raise QueryError(f"Unknown metric(s): {', '.join(unknown)}. Call list_metrics to see what is defined.")


@lru_cache(maxsize=256)
def dimensions_for(metric_names: tuple[str, ...]) -> list[str]:
    out = _run([MF, "list", "dimensions", "--metrics", ",".join(metric_names)])
    return [ln.strip("• ").strip() for ln in out.splitlines() if ln.strip().startswith("•")]


def _query_args(metric_names, group_by, where, order_by, limit) -> list[str]:
    args = [MF, "query", "--metrics", ",".join(metric_names)]
    if group_by:
        args += ["--group-by", ",".join(group_by)]
    if where:
        args += ["--where", where]
    if order_by:
        args += ["--order", ",".join(order_by)]
    if limit:
        args += ["--limit", str(limit)]
    return args


def query(metric_names, group_by=None, where=None, order_by=None, limit=None) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        path = tmp.name
    try:
        _run(_query_args(metric_names, group_by, where, order_by, limit) + ["--csv", path])
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    finally:
        os.unlink(path)


def explain(metric_names, group_by=None, where=None, order_by=None, limit=None) -> str:
    out = _run(_query_args(metric_names, group_by, where, order_by, limit) + ["--explain"])
    return out.split("🔎 SQL", 1)[-1].split("\n", 1)[-1].strip()
