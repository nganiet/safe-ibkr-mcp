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

    @app.tool()
    async def get_positions() -> list:
        """Open positions: ticker, shares, avg cost. (Live valuation requires market data — added later.)"""
        return await tools_read.positions(conn)

    @app.tool()
    async def get_open_orders() -> list:
        """Currently open orders with status and fill progress."""
        return await tools_read.open_orders(conn)

    @app.tool()
    async def get_order_status(order_id: str) -> dict:
        """Status of a single order by IBKR order id or perm id."""
        return await tools_read.order_status(conn, order_id)

    @app.tool()
    async def get_executions(since_iso: str) -> list:
        """Fills since an ISO-8601 timestamp (e.g. 2026-05-31T00:00:00+00:00)."""
        return await tools_read.executions(conn, since_iso)

    return app
