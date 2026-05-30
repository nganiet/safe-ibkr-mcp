"""Account reads. Imports ib_async; never mcp/FastMCP."""

import ib_async

from ibkr_mcp.core.models import AccountInfo


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
