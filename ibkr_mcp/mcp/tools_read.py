"""Read-tool logic — plain async functions, FastMCP-free for testability.

Takes an IBKRConnection. server.py wraps these in @app.tool() decorators.
"""

from ibkr_mcp.core.account import get_account_summary
from ibkr_mcp.core.connection import IBKRConnection


async def health(conn: IBKRConnection) -> dict:
    h = await conn.health()
    return {
        "connected": h.connected,
        "is_paper": conn.is_paper,
        "last_heartbeat_at": (h.last_heartbeat_at.isoformat() if h.last_heartbeat_at else None),
    }


async def account_summary(conn: IBKRConnection) -> dict:
    await conn.ensure_connected()
    acct = await get_account_summary(conn.ib)
    return {
        "total_value": acct.total_value,
        "cash": acct.cash,
        "buying_power": acct.buying_power,
        "positions_value": acct.positions_value,
        "unrealized_pnl": acct.unrealized_pnl,
    }
