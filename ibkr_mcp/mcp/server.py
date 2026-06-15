"""FastMCP server wiring — thin layer over core/ + tools_read + tools_write.

Imports the installed `mcp` SDK (top-level, not this subpackage) and core/.
Never imports ib_async directly.
"""

from mcp.server.fastmcp import FastMCP

from ibkr_mcp.core.connection import IBKRConnection
from ibkr_mcp.core.safety.guardrails import GuardrailPolicy
from ibkr_mcp.core.safety.idempotency import IdempotencyStore, PreviewTokenStore
from ibkr_mcp.core.safety.killswitch import KillSwitch
from ibkr_mcp.mcp import tools_read, tools_write
from ibkr_mcp.mcp.config import Config


def build_server(conn: IBKRConnection, config: Config | None = None) -> FastMCP:
    config = config if config is not None else Config()  # default: read-only
    app = FastMCP(
        "ibkr-mcp",
        instructions=(
            "Guarded Interactive Brokers access. Paper-trading by default. "
            + (
                "Read-only build."
                if config.read_only
                else "Writable build — orders go through preview_order then confirm_order."
            )
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
    async def get_cash_balances() -> list:
        """Cash per currency (e.g. USD, CAD) plus the consolidated BASE row. Surfaces a multi-currency split that get_account_summary (base-currency only) hides — e.g. a CAD-base account holding USD stock."""
        return await tools_read.cash_balances(conn)

    @app.tool()
    async def get_open_orders() -> list:
        """Currently open orders with status and fill progress."""
        return await tools_read.open_orders(conn)

    @app.tool()
    async def get_order_status(order_id: str) -> dict:
        """Status of a single OPEN order by IBKR order id or perm id. Completed (filled/cancelled) orders are not returned here — use get_executions for fills."""
        return await tools_read.order_status(conn, order_id)

    @app.tool()
    async def get_executions(since_iso: str) -> list:
        """Fills since an ISO-8601 timestamp (e.g. 2026-05-31T00:00:00+00:00)."""
        return await tools_read.executions(conn, since_iso)

    @app.tool()
    async def get_quote(ticker: str, delayed: bool = True) -> dict:
        """Snapshot quote (last/bid/ask/close). Delayed by default (free); set delayed=false for real-time (needs a paid IBKR subscription)."""
        return await tools_read.quote(conn, ticker, delayed=delayed)

    @app.tool()
    async def get_historical_bars(
        ticker: str, duration: str = "5 D", bar_size: str = "1 day"
    ) -> list:
        """Historical OHLCV bars (e.g. duration='5 D', bar_size='1 day')."""
        return await tools_read.historical_bars(conn, ticker, duration=duration, bar_size=bar_size)

    @app.tool()
    async def get_option_chain(ticker: str) -> dict:
        """Option expirations and strikes for the underlying (SMART exchange)."""
        return await tools_read.option_chain(conn, ticker)

    if not config.read_only:
        ctx = tools_write.WriteContext(
            policy=GuardrailPolicy(
                max_order_qty=config.max_order_qty,
                max_order_notional_usd=config.max_order_notional_usd,
                ticker_allowlist=config.ticker_allowlist,
                allow_live=config.allow_live,
            ),
            killswitch=KillSwitch(path=config.state_dir / "KILL"),
            idempotency=IdempotencyStore(db_path=config.state_dir / "state.db"),
            tokens=PreviewTokenStore(db_path=config.state_dir / "state.db"),
        )

        @app.tool()
        async def preview_order(
            symbol: str,
            side: str,
            order_type: str,
            quantity: str,
            limit_price: float | None = None,
            stop_price: float | None = None,
        ) -> dict:
            """Validate an order against guardrails, compute margin/commission, and return a single-use confirm_token. Places NOTHING."""
            return await tools_write.preview_order(
                conn,
                ctx,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                limit_price=limit_price,
                stop_price=stop_price,
            )

        @app.tool()
        async def confirm_order(confirm_token: str) -> dict:
            """Place the order previewed under confirm_token. Single-use + idempotent: retrying with the same token returns the original result and never double-places. If placement fails the token is consumed — re-run preview_order to retry."""
            return await tools_write.confirm_order(conn, ctx, confirm_token=confirm_token)

        @app.tool()
        async def cancel_order(order_id: str) -> dict:
            """Cancel an open order by IBKR order id or perm id."""
            return await tools_write.cancel_order_tool(conn, ctx, order_id=order_id)

    return app
