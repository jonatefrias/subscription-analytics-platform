"""MCP server: governed metric access for an AI analyst.

Tools (all read-only):
  list_metrics      the metric catalog with one-line definitions and kind (snapshot, flow, ratio...)
  describe_metric   the full definition of one metric and the dimensions it can be grouped by
  query_metrics     runs a semantic-layer query and returns rows plus the SQL MetricFlow generated
  verify_number     re-derives a number through an independent path before it is reported

There is deliberately no raw-SQL tool: every number comes from a definition the data team owns.

Run:  python -m semantic_agent        (stdio; see .mcp.json for Claude Code)
"""

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from semantic_agent import metricflow as mf
from semantic_agent.verify import verify

INSTRUCTIONS = """You answer business questions about Matchday+, a fictional sports-streaming \
subscription app, using only the metrics in this server.

Rules:
1. Start from list_metrics. If no defined metric answers the question, say so and name the closest
   metrics; never approximate with a different metric without saying it is a different metric.
2. Before using a metric you have not used in this conversation, read its definition with
   describe_metric, and state the definition in one line in your answer.
3. Snapshot metrics (MRR, paying customers) are balances: at quarter or year grain they are the
   closing month, never a sum of months.
4. Before you state a number in an answer, confirm it with verify_number. Report only confirmed
   numbers; if a number cannot be verified, say so next to it.
5. Show your work: list the metrics, grain, filters and the period you used."""

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
MAX_ROWS = 500

server = MCPServer(name="subscription-metrics", instructions=INSTRUCTIONS)


def _kind(metric: dict) -> str:
    if metric["type"] == "ratio":
        return "ratio"
    if metric["type"] == "derived":
        return "derived"
    measure_name = metric["type_params"]["measure"]["name"]
    measure, _ = mf.measures()[measure_name]
    return "snapshot" if measure.get("non_additive_dimension") else "flow"


@server.tool(annotations=READ_ONLY)
def list_metrics() -> list[dict[str, str]]:
    """List every defined metric with its label, kind (snapshot, flow, ratio, derived) and description."""
    return [
        {"name": name, "label": m.get("label") or name, "kind": _kind(m), "description": m.get("description") or ""}
        for name, m in sorted(mf.metrics().items())
    ]


@server.tool(annotations=READ_ONLY)
def describe_metric(name: str) -> dict[str, Any]:
    """Full definition of one metric: type, inputs, filter, additivity, source mart and group-by dimensions."""
    mf.check_metric_names([name])
    metric = mf.metrics()[name]
    params = metric["type_params"]
    detail: dict[str, Any] = {
        "name": name,
        "label": metric.get("label"),
        "description": metric.get("description"),
        "type": metric["type"],
        "kind": _kind(metric),
        "filter": (metric.get("filter") or {}).get("where_filters", [{}])[0].get("where_sql_template")
        if metric.get("filter")
        else None,
    }
    if metric["type"] == "simple":
        measure, sm = mf.measures()[params["measure"]["name"]]
        detail["measure"] = {
            "name": measure["name"],
            "aggregation": measure["agg"],
            "expression": measure.get("expr") or measure["name"],
            "non_additive_over": (measure.get("non_additive_dimension") or {}).get("name"),
            "fill_nulls_with": params["measure"].get("fill_nulls_with"),
        }
        detail["source"] = sm["node_relation"]["relation_name"]
    elif metric["type"] == "ratio":
        detail["numerator"] = params["numerator"]["name"]
        detail["denominator"] = params["denominator"]["name"]
    elif metric["type"] == "derived":
        detail["expression"] = params["expr"]
        detail["inputs"] = [m["name"] for m in params["metrics"]]
    detail["group_by_dimensions"] = mf.dimensions_for((name,))
    return detail


@server.tool(annotations=READ_ONLY)
def query_metrics(
    metrics: list[str],
    group_by: list[str] | None = None,
    where: str | None = None,
    order_by: list[str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Query metrics through the semantic layer.

    group_by: e.g. ["metric_time__month", "customer__market_code"]; time grains are
      metric_time__day | __week | __month | __quarter | __year.
    where: MetricFlow filter, e.g. "{{ TimeDimension('metric_time', 'month') }} >= '2025-01-01'"
      or "{{ Dimension('customer__market_code') }} = 'US'".
    order_by: e.g. ["metric_time__month"] or ["-mrr"] for descending.
    Returns the rows, the generated SQL and whether the result was cut at the row limit.
    """
    mf.check_metric_names(metrics)
    limit = max(1, min(limit, MAX_ROWS))
    rows = mf.query(metrics, group_by, where, order_by, limit + 1)
    sql = mf.explain(metrics, group_by, where, order_by, limit)
    return {"rows": rows[:limit], "row_count": min(len(rows), limit), "truncated": len(rows) > limit, "sql": sql}


@server.tool(annotations=READ_ONLY)
def verify_number(metric: str, grain: str, period_start: str, reported_value: float) -> dict[str, Any]:
    """Re-derive one number through an independent path before reporting it.

    metric: a metric name; grain: month | quarter | year; period_start: first day, e.g. '2025-07-01';
    reported_value: the value you intend to report (company total, no dimension filters).
    Returns confirmed / mismatch / unverifiable, the re-derived value and the method used.
    """
    mf.check_metric_names([metric])
    return verify(metric, grain, period_start, reported_value)


@server.prompt()
def analyst(question: str) -> str:
    """Answer a business question with governed metrics, verified numbers and stated definitions."""
    return f"{INSTRUCTIONS}\n\nQuestion: {question}"


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
