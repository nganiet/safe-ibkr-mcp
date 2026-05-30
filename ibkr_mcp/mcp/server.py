"""FastMCP server wiring — thin layer over core/ + tools_read.

Imports the installed `mcp` SDK (top-level, not this subpackage) and core/.
Never imports ib_async directly.
"""

from mcp.server.fastmcp import FastMCP

from ibkr_mcp.core.connection import IBKRConnection
from ibkr_mcp.mcp import tools_read


def build_server(conn: IBKRConnection) -> FastMCP:
    app = FastMCP(
        "ibkr-mcp",
        instructions=(
            "Guarded Interactive Brokers access. Paper-trading by default. "
            "Read-only tools only in this build."
        ),
    )

    @app.tool()
    async def ibkr_health() -> dict:
        """Connection state to IB Gateway: connected, paper vs live, last heartbeat."""
        return await tools_read.health(conn)

    @app.tool()
    async def get_account_summary() -> dict:
        """Account summary: net liquidation, cash, buying power, positions value, unrealized P&L."""
        return await tools_read.account_summary(conn)

    return app
