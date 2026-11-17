"""Pull-request impact report from dbt state comparison.

Compares the dbt manifest of the current checkout with the manifest of the base branch and
writes a Markdown report: which models changed (state:modified), everything downstream of them
(state:modified+), and which semantic-layer metrics and saved queries sit on top of the
affected models. Reviewers see the blast radius of a change before reading the diff.

Usage (from transform/, after `dbt parse` in both checkouts):
    python ../scripts/impact_report.py --state ../base/transform/target > impact.md
"""

import argparse
import json
import os
import subprocess
from collections import defaultdict


def dbt_ls(selector: str, state: str) -> list[dict]:
    result = subprocess.run(
        [
            "dbt",
            "--quiet",
            "ls",
            "--select",
            selector,
            "--state",
            state,
            "--output",
            "json",
            "--output-keys",
            "unique_id",
            "resource_type",
            "name",
            "original_file_path",
        ],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "DBT_PROFILES_DIR": os.environ.get("DBT_PROFILES_DIR", ".")},
    )
    return [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]


def downstream_metrics(manifest_path: str, affected_models: set[str]) -> dict[str, list[str]]:
    """Metric name -> affected models it depends on (through its semantic model)."""
    with open(manifest_path) as f:
        manifest = json.load(f)
    semantic_model_of_measure: dict[str, str] = {}
    model_of_semantic_model: dict[str, str] = {}
    for sm in manifest.get("semantic_models", {}).values():
        model = next((n.split(".")[-1] for n in sm["depends_on"]["nodes"]), None)
        model_of_semantic_model[sm["name"]] = model
        for measure in sm.get("measures", []):
            semantic_model_of_measure[measure["name"]] = sm["name"]

    metrics = manifest.get("metrics", {})
    by_name = {m["name"]: m for m in metrics.values()}

    def measures(metric_name: str, seen: set[str]) -> set[str]:
        if metric_name in seen:
            return set()
        seen.add(metric_name)
        m = by_name[metric_name]
        found = {i["name"] for i in m["type_params"].get("input_measures", [])}
        for parent in m["type_params"].get("metrics", []) or []:
            found |= measures(parent["name"], seen)
        return found

    hits: dict[str, list[str]] = defaultdict(list)
    for name in by_name:
        for measure in measures(name, set()):
            model = model_of_semantic_model.get(semantic_model_of_measure.get(measure, ""))
            if model in affected_models and model not in hits[name]:
                hits[name].append(model)
    return dict(sorted(hits.items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, help="target/ folder of the base branch")
    args = parser.parse_args()

    modified = dbt_ls("state:modified", args.state)
    impacted = dbt_ls("state:modified+", args.state)
    modified_ids = {n["unique_id"] for n in modified}
    downstream = [n for n in impacted if n["unique_id"] not in modified_ids]

    def models(nodes):
        return sorted({n["name"] for n in nodes if n["resource_type"] in ("model", "seed", "snapshot")})

    affected = set(models(impacted))
    metrics = downstream_metrics(os.path.join("target", "manifest.json"), affected)
    tests = [n for n in impacted if n["resource_type"] in ("test", "unit_test")]

    print("## dbt impact report\n")
    if not impacted:
        print("No dbt resources changed versus the base branch.")
        return
    definitions = sorted(
        {n["name"] for n in modified if n["resource_type"] in ("metric", "semantic_model", "saved_query")}
    )
    print(
        f"**{len(models(modified))} models changed** · **{len(definitions)} semantic definitions changed** · "
        f"**{len(models(downstream))} downstream** · **{len(metrics)} metrics on affected models** · "
        f"{len(tests)} tests in scope\n"
    )
    print("| Changed | Path |\n|---|---|")
    for n in sorted(modified, key=lambda n: n["original_file_path"]):
        if n["resource_type"] not in ("test", "unit_test"):
            print(f"| `{n['name']}` ({n['resource_type']}) | `{n['original_file_path']}` |")
    if models(downstream):
        print("\n**Downstream models rebuilt:** " + ", ".join(f"`{m}`" for m in models(downstream)))
    if metrics:
        print("\n**Semantic-layer metrics on top of affected models:**\n")
        for metric, via in metrics.items():
            print(f"- `{metric}` (via {', '.join(f'`{m}`' for m in via)})")
    print(
        "\n<sub>Against a persistent warehouse this selection drives slim CI: "
        "`dbt build --select state:modified+ --defer --state <prod manifest>`.</sub>"
    )


if __name__ == "__main__":
    main()
