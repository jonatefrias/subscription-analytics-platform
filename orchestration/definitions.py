"""Dagster orchestration for the subscription analytics platform.

Asset graph
  raw/*                 the ten source extracts, produced by the synthetic generator
  dbt models            one asset per model; every dbt test becomes an asset check
  semantic reconciliation   an asset check on rpt_mrr_bridge that runs
                        scripts/check_semantic_layer.py (metric layer == marts)

Operations
  daily_refresh         job that refreshes everything, scheduled 06:00 UTC
  raw freshness policy  raw extracts warn after 24 hours without a refresh and fail after 26

Run locally from the repo root:  dagster dev -m orchestration.definitions
"""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pyarrow.parquet as pq
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetExecutionContext,
    AssetSelection,
    AssetSpec,
    Config,
    Definitions,
    FreshnessPolicy,
    MaterializeResult,
    ScheduleDefinition,
    asset_check,
    define_asset_job,
    multi_asset,
)
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets, get_asset_key_for_model

# PROJECT_ROOT lets tests run the whole graph against a throw-away copy of the repo.
ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[1]))
TRANSFORM_DIR = ROOT / "transform"
RAW_DIR = ROOT / "data" / "raw"  # dbt reads it as ../data/raw from transform/

RAW_TABLES = {
    "crm_customers": "CRM export, one row per profile version.",
    "billing_plans": "Plan catalogue.",
    "billing_plan_prices": "Price list with validity ranges (SCD2).",
    "billing_subscriptions": "Subscriptions with trial, cancellation and reason.",
    "billing_payments": "Every charge attempt, failed attempts and retries included.",
    "finance_fx_rates": "Daily FX rates, units per USD.",
    "app_playback_events": "Client playback events (at-least-once delivery).",
    "marketing_spend": "Daily paid media spend by market and channel.",
    "experiments_assignments": "Experiment variant assignment at signup.",
    "ga4_events": "GA4 web stream in the BigQuery export layout.",
}

dbt_project = DbtProject(
    project_dir=TRANSFORM_DIR,
    profiles_dir=TRANSFORM_DIR,
    target=os.environ.get("DBT_TARGET", "dev"),
)
if not dbt_project.manifest_path.exists():  # first run on a fresh checkout
    DbtCliResource(project_dir=dbt_project).cli(["--quiet", "parse"], target_path=Path("target")).wait()


# ------------------------------------------------------------------ raw layer
class GeneratorConfig(Config):
    scale: float = 1.0
    seed: int = 42


RAW_FRESHNESS = FreshnessPolicy.time_window(fail_window=timedelta(hours=26), warn_window=timedelta(hours=24))


@multi_asset(
    specs=[
        AssetSpec(["raw", name], description=desc, group_name="raw", kinds={"parquet"}, freshness_policy=RAW_FRESHNESS)
        for name, desc in RAW_TABLES.items()
    ],
)
def raw_sources(context: AssetExecutionContext, config: GeneratorConfig):
    """Lands the raw extracts. In production this would be the ingestion tool (Fivetran,
    Airbyte, a Lambda); here the synthetic generator plays that role."""
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "generator" / "generate.py"),
            "--out",
            str(RAW_DIR),
            "--scale",
            str(config.scale),
            "--seed",
            str(config.seed),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    for name in RAW_TABLES:
        rows = pq.read_metadata(RAW_DIR / f"{name}.parquet").num_rows
        yield MaterializeResult(asset_key=["raw", name], metadata={"rows": rows})


# ------------------------------------------------------------------ dbt layer
class LayerTranslator(DagsterDbtTranslator):
    """Groups assets by layer (staging, intermediate) and by mart domain (finance, product...)."""

    def get_asset_spec(self, manifest, unique_id, project):
        spec = super().get_asset_spec(manifest, unique_id, project)
        props = manifest["nodes"].get(unique_id) or manifest["sources"].get(unique_id) or {}
        if props.get("resource_type") == "source":
            return spec.replace_attributes(group_name="raw")
        fqn = props.get("fqn", [])
        layer = fqn[1] if len(fqn) > 2 else "reference"
        group = fqn[2] if layer == "marts" and len(fqn) > 3 else layer
        return spec.replace_attributes(group_name=group)


@dbt_assets(manifest=dbt_project.manifest_path, project=dbt_project, dagster_dbt_translator=LayerTranslator())
def analytics_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    """`dbt build`: models, seeds, data tests, unit tests and contracts, in dependency order."""
    yield from dbt.cli(["build"], context=context).stream()


# ------------------------------------------------------------------ checks
@asset_check(
    asset=get_asset_key_for_model([analytics_dbt_assets], "rpt_mrr_bridge"),
    description="Semantic-layer metrics must equal the MRR bridge, every month, and quarterly MRR "
    "must equal the closing month (snapshot measures).",
    blocking=False,
)
def semantic_layer_reconciles() -> AssetCheckResult:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_semantic_layer.py")],
        cwd=TRANSFORM_DIR,
        capture_output=True,
        text=True,
        check=False,  # a failure is the check result
        env={**os.environ, "DBT_PROFILES_DIR": str(TRANSFORM_DIR)},
    )
    output = (result.stdout + result.stderr).strip()
    return AssetCheckResult(
        passed=result.returncode == 0,
        severity=AssetCheckSeverity.ERROR,
        metadata={"output": output[-2000:]},
    )


# ------------------------------------------------------------------ jobs
daily_refresh = define_asset_job(
    "daily_refresh",
    selection=AssetSelection.all(),
    description="Land the raw extracts, run dbt build and reconcile the semantic layer.",
)

defs = Definitions(
    assets=[raw_sources, analytics_dbt_assets],
    asset_checks=[semantic_layer_reconciles],
    jobs=[daily_refresh],
    schedules=[ScheduleDefinition(job=daily_refresh, cron_schedule="0 6 * * *", execution_timezone="UTC")],
    resources={"dbt": DbtCliResource(project_dir=dbt_project)},
)
