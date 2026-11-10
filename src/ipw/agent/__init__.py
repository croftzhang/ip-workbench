"""The release 2 assistant. Optional: install it with ``pip install -e ".[agent]"``."""

from __future__ import annotations

INSTALL_HINT = 'this command needs the agent extra: pip install -e ".[agent]"'


def mcp_main() -> None:
    """Entry point of ``ipw-mcp``: one line, not a traceback, when the extra is not installed."""
    try:
        from ipw.agent.mcp_server import main
    except ModuleNotFoundError as err:
        raise SystemExit(f"Error: {INSTALL_HINT} (missing module: {err.name})") from None
    main()
