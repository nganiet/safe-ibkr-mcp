"""Read-tool logic — plain async functions, FastMCP-free for testability.

Takes an IBKRConnection. server.py wraps these in @app.tool() decorators.
"""

from datetime import datetime, timezone

from ibkr_mcp.core.account import get_account_summary, get_positions
from ibkr_mcp.core.connection import IBKRConnection
from ibkr_mcp.core.market_data import get_historical_bars, get_option_chain, get_quote
from ibkr_mcp.core.models import OrderUpdate, Symbol
from ibkr_mcp.core.orders import get_executions, get_open_orders, get_order_status


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


def _update_to_dict(u: OrderUpdate) -> dict:
    return {
        "order_id": u.order_id,
        "status": u.status.value,
        "filled_quantity": str(u.filled_quantity),
        "fill_price": u.fill_price,
        "broker_order_id": u.broker_order_id,
        "timestamp": u.timestamp.isoformat(),
    }


async def positions(conn) -> list[dict]:
    await conn.ensure_connected()
    out = []
    for p in await get_positions(conn.ib):
        out.append(
            {
                "ticker": p.ticker,
                "shares": str(p.shares),
                "avg_cost": p.avg_cost,
                "current_price": p.current_price,
                "market_value": p.market_value,
                "unrealized_pnl": p.unrealized_pnl,
                "valuation_available": False,  # live price is M3b (needs market data)
            }
        )
    return out


async def open_orders(conn) -> list[dict]:
    await conn.ensure_connected()
    return [_update_to_dict(u) for u in await get_open_orders(conn.ib)]


async def order_status(conn, order_id: str) -> dict:
    await conn.ensure_connected()
    status = await get_order_status(conn.ib, order_id)
    return {"order_id": order_id, "status": status.value}


async def executions(conn, since_iso: str) -> list[dict]:
    await conn.ensure_connected()
    since = datetime.fromisoformat(since_iso)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)  # treat naive ISO as UTC
    return [_update_to_dict(u) for u in await get_executions(conn.ib, since)]


async def quote(conn, ticker: str, *, delayed: bool = True) -> dict:
    await conn.ensure_connected()
    return await get_quote(conn.ib, Symbol.equity(ticker), delayed=delayed)


async def historical_bars(
    conn, ticker: str, *, duration: str = "5 D", bar_size: str = "1 day"
) -> list[dict]:
    await conn.ensure_connected()
    return await get_historical_bars(
        conn.ib, Symbol.equity(ticker), duration=duration, bar_size=bar_size
    )


async def option_chain(conn, ticker: str) -> dict:
    await conn.ensure_connected()
    return await get_option_chain(conn.ib, Symbol.equity(ticker))
