"""Account reads. Imports ib_async; never mcp/FastMCP."""

from decimal import Decimal

import ib_async

from ibkr_mcp.core.models import AccountInfo, CashBalance, PositionInfo


async def get_account_summary(ib: "ib_async.IB") -> AccountInfo:
    rows = await ib.accountSummaryAsync()
    values = {row.tag: row.value for row in rows}

    def num(tag: str) -> float:
        try:
            return float(values.get(tag, 0.0))
        except (TypeError, ValueError):
            return 0.0

    # Base currency = the currency the summary figures are reported in. accountSummary
    # stamps it on every row; NetLiquidation is the reliable anchor (e.g. "CAD").
    base_currency = next(
        (
            getattr(row, "currency", "")
            for row in rows
            if row.tag == "NetLiquidation" and getattr(row, "currency", "")
        ),
        "",
    )

    return AccountInfo(
        total_value=num("NetLiquidation"),
        cash=num("TotalCashValue"),
        buying_power=num("BuyingPower"),
        positions_value=num("GrossPositionValue"),
        unrealized_pnl=num("UnrealizedPnL"),
        base_currency=base_currency,
    )


async def get_cash_balances(ib: "ib_async.IB") -> list[CashBalance]:
    """Per-currency cash ledger (e.g. USD, CAD) plus the consolidated BASE row.

    get_account_summary reports cash/positions in the account BASE currency only,
    which hides a multi-currency split: a CAD-base account holding USD stock shows
    the USD value rolled into GrossPositionValue at the FX rate, and TotalCashValue
    collapses every currency into one base figure. This surfaces the raw CashBalance
    rows so the USD vs CAD split is visible.
    """
    values = ib.accountValues()
    if not any(v.tag == "CashBalance" for v in values):
        # accountValues() is empty until account updates are subscribed; the summary
        # path uses accountSummaryAsync and may never have triggered the ledger feed.
        accounts = ib.managedAccounts()
        await ib.reqAccountUpdatesAsync(accounts[0] if accounts else "")
        values = ib.accountValues()

    out: list[CashBalance] = []
    for v in values:
        if v.tag != "CashBalance":
            continue
        try:
            amount = float(v.value)
        except (TypeError, ValueError):
            continue
        out.append(CashBalance(currency=v.currency, amount=amount))
    return out


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
