"""Account reads. Imports ib_async; never mcp/FastMCP."""

from decimal import Decimal

import ib_async

from ibkr_mcp.core.models import AccountInfo, PositionInfo


async def get_account_summary(ib: "ib_async.IB") -> AccountInfo:
    rows = await ib.accountSummaryAsync()
    values = {row.tag: row.value for row in rows}

    def num(tag: str) -> float:
        try:
            return float(values.get(tag, 0.0))
        except (TypeError, ValueError):
            return 0.0

    return AccountInfo(
        total_value=num("NetLiquidation"),
        cash=num("TotalCashValue"),
        buying_power=num("BuyingPower"),
        positions_value=num("GrossPositionValue"),
        unrealized_pnl=num("UnrealizedPnL"),
    )


async def get_positions(ib) -> list[PositionInfo]:
    # ib.positions() is populated at connect (connectAsync fetches POSITIONS).
    # Live valuation (price/market_value/uPnL) needs market data — added in M3b.
    return [
        PositionInfo(
            ticker=p.contract.symbol,
            shares=Decimal(str(p.position)),
            avg_cost=float(p.avgCost),
            current_price=0.0,
            market_value=0.0,
            unrealized_pnl=0.0,
        )
        for p in ib.positions()
    ]
