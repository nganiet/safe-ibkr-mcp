"""Symbol -> ib_async Contract translation. Imports ib_async; never mcp/FastMCP.

M3a covers equities only; option-chain resolution is M3b.
"""

from ib_async import Contract, Stock

from ibkr_mcp.core.models import AssetClass, Symbol


def to_ib_contract(symbol: Symbol) -> Contract:
    if symbol.asset_class == AssetClass.EQUITY:
        return Stock(symbol.code, symbol.exchange or "SMART", "USD")
    raise ValueError(f"Unsupported asset class for M3a: {symbol.asset_class}")


async def qualify(ib, symbol: Symbol) -> Contract:
    qualified = await ib.qualifyContractsAsync(to_ib_contract(symbol))
    if not qualified:
        raise ValueError(f"could not qualify contract for {symbol.code}")
    return qualified[0]
