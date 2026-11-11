"""Release 2, build step 1: the optional MCP server (docs/AGENT_DESIGN.md, AD-3).

The evidence the build plan asks for: the MCP server lists the same tools. The
design adds that the two ways in must stay identical, so a call through the
server is compared with the same call made in process.
"""

import sys

import pytest

import ipw

tools = pytest.importorskip("ipw.agent.tools", reason='needs the agent extra: pip install -e ".[agent]"')
server = pytest.importorskip(
    "ipw.agent.mcp_server", reason='needs the agent extra: pip install -e ".[agent]"'
)
anyio = pytest.importorskip("anyio")
mcp = pytest.importorskip("mcp")

BREAKDOWN = {"scenario": "up_200", "by": "designation"}
SHARE = {
    "operation": "ratio",
    "as_percent": True,
    "label": "AFS share of the loss",
    "cells": [
        {"result": "r2", "row": "AFS", "column": "d_value_mm"},
        {"result": "r2", "row": "Total", "column": "d_value_mm"},
    ],
}
CALLS = [
    ("limit_status", {}),
    ("scenario_breakdown", BREAKDOWN),
    ("aggregate", SHARE),
    ("limit_remedy", {"limit": "AOCI_UP200", "tenors": [5]}),
    ("portfolio_summary", {"by": "sector"}),  # rejected by the schema
    ("position_detail", {"position_id": "NOPE"}),  # refused by the engine
    ("no_such_tool", {}),
]


def session(target, calls=()):
    """Connect a client to a server, list its tools and make the calls in order."""

    async def talk():
        async with mcp.Client(target) as client:
            listed = (await client.list_tools()).tools
            return (
                client.server_info,
                listed,
                [await client.call_tool(name, arguments) for name, arguments in calls],
            )

    return anyio.run(talk)


def test_the_server_lists_the_same_tools(wb):
    toolbox = tools.Toolbox(wb)
    info, listed, _ = session(server.build_server(toolbox))
    assert info.name == "ip-workbench" and info.version == ipw.__version__
    assert [tool.name for tool in listed] == [spec.name for spec in toolbox.specs]
    for tool, spec in zip(listed, toolbox.specs):
        assert tool.description == spec.description
        assert tool.input_schema == spec.parameters
        assert tool.annotations.read_only_hint is True


def test_a_call_through_the_server_equals_the_call_in_process(wb):
    _, _, served = session(server.build_server(tools.Toolbox(wb)), CALLS)
    direct = tools.Toolbox(wb)
    for answer, (name, arguments) in zip(served, CALLS):
        expected = direct.call(name, arguments)
        assert answer.is_error == (not expected.ok), name
        assert answer.structured_content == expected.to_dict(), name
        assert [block.text for block in answer.content] == [expected.to_text()], name
    assert [result.ok for result in direct.results] == [True, True, True, True, False, False, False]
    assert direct.results[2].table().rows["AFS share of the loss"]["value"] == pytest.approx(41.99, abs=0.005)


def test_the_server_runs_as_a_separate_process_on_standard_streams(root):
    """The way another MCP client starts it: the command ``ipw-ai mcp``."""
    command = mcp.StdioServerParameters(
        command=sys.executable, args=["-m", "ipw.agent.cli", "--root", str(root), "mcp"]
    )
    excess = {
        "operation": "difference",
        "label": "beyond the limit",
        "cells": [
            {"result": "r1", "row": "AOCI_UP200", "column": "value"},
            {"result": "r1", "row": "AOCI_UP200", "column": "min"},
        ],
    }
    _, listed, (limits, beyond) = session(command, [("limit_status", {}), ("aggregate", excess)])
    assert len(listed) == 15
    assert limits.structured_content["tables"][0]["rows"]["AOCI_UP200"]["status"] == "BREACH"
    figure = beyond.structured_content["tables"][0]
    assert figure["units"] == {"value": "USD millions"}
    assert figure["rows"]["beyond the limit"]["value"] == pytest.approx(-15.99, abs=0.005)


def test_ipw_ai_mcp_without_the_extra_says_what_to_install(monkeypatch, capsys):
    import ipw.agent
    from ipw.agent import cli

    monkeypatch.delitem(sys.modules, "ipw.agent.mcp_server")  # so that the command imports it afresh
    monkeypatch.delattr(ipw.agent, "mcp_server")
    monkeypatch.setitem(sys.modules, "mcp", None)  # makes "import mcp" fail as if it were not installed
    monkeypatch.setattr(sys, "argv", ["ipw-ai", "mcp"])
    with pytest.raises(SystemExit) as stop:
        cli.main()
    assert stop.value.code == 1
    message = " ".join(capsys.readouterr().err.split())
    assert message == 'Error: AI mode is an optional install: pip install -e ".[agent]" (missing module: mcp)'
