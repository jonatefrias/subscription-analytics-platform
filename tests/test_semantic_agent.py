"""The MCP server, exercised over the real protocol (stdio), the way Claude Code runs it.

Needs a built warehouse (`dbt build`), like the semantic-layer reconciliation; CI runs it
after the build step. The checks are about behaviour an analyst relies on:
  * only read-only tools are exposed, and there is no raw-SQL tool
  * a query returns rows and the SQL that produced them
  * verify_number confirms a correct number and rejects a wrong one
  * an unknown metric is refused with a useful message instead of a guess
"""

import json
import os
import sys
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO = Path(__file__).resolve().parents[1]


def call_server(steps):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "semantic_agent"],
        cwd=str(REPO),
        env={**os.environ, "DBT_PROFILES_DIR": str(REPO / "transform")},
    )

    async def run():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await steps(session)

    return anyio.run(run)


def payload(result):
    assert not result.is_error, result.content
    if result.structured_content is not None:
        return result.structured_content.get("result", result.structured_content)
    return json.loads(result.content[0].text)


def test_tools_are_read_only_and_governed():
    async def steps(session):
        return (await session.list_tools()).tools

    tools = {t.name: t for t in call_server(steps)}
    assert set(tools) == {"list_metrics", "describe_metric", "query_metrics", "verify_number"}
    assert all(t.annotations and t.annotations.read_only_hint for t in tools.values())


def test_query_and_verify_round_trip():
    async def steps(session):
        query = payload(
            await session.call_tool(
                "query_metrics",
                {"metrics": ["mrr"], "group_by": ["metric_time__quarter"], "order_by": ["metric_time__quarter"]},
            )
        )
        last = query["rows"][-2]  # last complete quarter in the default dataset
        quarter = last["metric_time__quarter"][:10]
        value = float(last["mrr"])
        good = payload(
            await session.call_tool(
                "verify_number", {"metric": "mrr", "grain": "quarter", "period_start": quarter, "reported_value": value}
            )
        )
        bad = payload(
            await session.call_tool(
                "verify_number",
                {"metric": "mrr", "grain": "quarter", "period_start": quarter, "reported_value": value * 3},
            )
        )
        return query, good, bad

    query, good, bad = call_server(steps)
    assert query["rows"] and "select" in query["sql"].lower()
    assert good["status"] == "confirmed"
    assert bad["status"] == "mismatch"  # summing three months of a snapshot would land here


def test_unknown_metric_is_refused():
    async def steps(session):
        return await session.call_tool("describe_metric", {"name": "revenue_per_fan"})

    result = call_server(steps)
    assert result.is_error
    assert "list_metrics" in result.content[0].text
