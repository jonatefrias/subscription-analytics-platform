"""Orchestration tests.

test_definitions_load       the Dagster code location loads and the graph has the expected shape
test_daily_refresh_end_to_end
    runs the real `daily_refresh` job on a throw-away copy of the repo with a small dataset:
    generator -> dbt build (every dbt test as an asset check) -> semantic-layer reconciliation.
    Nothing in the working copy (data/, warehouse) is touched.
"""

import importlib
import os
import shutil
import sys
from pathlib import Path

import pytest
from dagster import AssetKey, DagsterInstance, Definitions

REPO = Path(__file__).resolve().parents[1]


def load_definitions(project_root: Path, duckdb_path: Path):
    os.environ["PROJECT_ROOT"] = str(project_root)
    os.environ["DUCKDB_PATH"] = str(duckdb_path)
    os.environ["DBT_TARGET"] = "ci"
    sys.modules.pop("orchestration.definitions", None)
    return importlib.import_module("orchestration.definitions").defs


@pytest.fixture()
def repo_copy(tmp_path: Path) -> Path:
    for folder in ("generator", "scripts", "orchestration"):
        shutil.copytree(REPO / folder, tmp_path / folder)
    shutil.copytree(
        REPO / "transform", tmp_path / "transform", ignore=shutil.ignore_patterns("target", "logs", ".user.yml")
    )
    return tmp_path


def test_definitions_load(repo_copy: Path, tmp_path: Path):
    defs = load_definitions(repo_copy, tmp_path / "warehouse.duckdb")
    Definitions.validate_loadable(defs)
    graph = defs.resolve_asset_graph()
    keys = set(graph.get_all_asset_keys())
    assert AssetKey(["raw", "ga4_events"]) in keys
    assert AssetKey(["finance", "rpt_mrr_bridge"]) in keys
    # dbt models depend on the raw assets produced by the generator
    assert AssetKey(["raw", "crm_customers"]) in graph.get(AssetKey(["staging", "stg_crm__customers"])).parent_keys
    assert any(k.name == "semantic_layer_reconciles" for k in graph.asset_check_keys)


def test_daily_refresh_end_to_end(repo_copy: Path, tmp_path: Path):
    defs = load_definitions(repo_copy, tmp_path / "warehouse.duckdb")
    job = defs.resolve_job_def("daily_refresh")
    result = job.execute_in_process(
        run_config={"ops": {"raw_sources": {"config": {"scale": 0.2, "seed": 7}}}},
        instance=DagsterInstance.ephemeral(),
    )
    assert result.success

    evaluations = result.get_asset_check_evaluations()
    failed = [e.check_name for e in evaluations if not e.passed]
    assert not failed, f"failed checks: {failed}"
    assert any(e.check_name == "semantic_layer_reconciles" for e in evaluations)
    assert len(evaluations) > 80  # dbt tests surfaced as asset checks
