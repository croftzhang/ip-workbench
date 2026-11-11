"""Optional MCP server: the tools of ``ipw.agent.tools`` for any MCP client.

``ipw-ai mcp`` speaks the Model Context Protocol on standard input and output.
It adds nothing of its own: the names, descriptions, argument schemas and results
all come from the same ``Toolbox`` the assistant uses in its own process, and a
test keeps the two ways in identical.

The server is one run in the sense of the toolbox: results are numbered from
``r1`` for as long as it is up, so a client can pass earlier figures to
``aggregate``. Every tool is read-only; nothing is executed or booked.

Written for version 2 of the MCP Python SDK (the low-level ``Server`` with
handlers given to its constructor).
"""

from __future__ import annotations

from pathlib import Path

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from ipw import Workbench, __version__
from ipw.agent.tools import Toolbox, ToolSpec

NAME = "ip-workbench"
INSTRUCTIONS = (
    "Read-only analytics on one investment portfolio of agency MBS and Treasuries, with its swap hedges. "
    "Every figure comes from a deterministic valuation engine. Results of limit_remedy, size_hedge and "
    "what_if are indicative proposals: nothing is traded, booked or approved. Use aggregate for any sum, "
    "difference or ratio of figures from earlier results."
)


def _listed(spec: ToolSpec) -> types.Tool:
    return types.Tool(
        name=spec.name,
        description=spec.description,
        input_schema=spec.parameters,
        annotations=types.ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )


def build_server(toolbox: Toolbox) -> Server:
    """An MCP server that lists and runs the tools of one toolbox."""

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[_listed(spec) for spec in toolbox.specs])

    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        result = toolbox.call(params.name, params.arguments)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result.to_text())],
            structured_content=result.to_dict(),
            is_error=not result.ok,
        )

    return Server(
        NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


async def serve(root: Path | None = None) -> None:
    """Load the book once and serve it on standard input and output until the client leaves."""
    server = build_server(Toolbox(Workbench.load(root)))
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run(root: Path | None = None) -> None:
    """What ``ipw-ai mcp`` does: serve until the client closes the connection."""
    anyio.run(serve, root)
