"""Market data reads — quotes, historical bars, option chains. Entitlement-aware.

Defaults to DELAYED data (reqMarketDataType(3)), which IBKR serves free (no
subscription). Real-time (type 1) needs a paid subscription. When no data is
available at all (all values nan / empty), raises MarketDataNotEntitled.
Imports ib_async; never mcp/FastMCP.
"""

import math

from ibkr_mcp.core.contracts import qualify
from ibkr_mcp.core.errors import MarketDataNotEntitled
from ibkr_mcp.core.models import Symbol


def _num(x) -> float | None:
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    return float(x)


async def get_quote(ib, symbol: Symbol, *, delayed: bool = True) -> dict:
    ib.reqMarketDataType(3 if delayed else 1)  # 3 = delayed (free), 1 = real-time (paid)
    contract = await qualify(ib, symbol)
    tickers = await ib.reqTickersAsync(contract)
    t = tickers[0]
    last, bid, ask = _num(t.last), _num(t.bid), _num(t.ask)
    close, mark = _num(t.close), _num(getattr(t, "markPrice", None))
    if last is None and bid is None and ask is None and close is None and mark is None:
        raise MarketDataNotEntitled(
            f"No market data for {symbol.code} — not subscribed and no delayed data available."
        )
    return {
        "ticker": symbol.code, "last": last, "bid": bid, "ask": ask,
        "close": close, "mark_price": mark,
        "market_data_type": getattr(t, "marketDataType", None), "delayed": delayed,
    }


async def get_historical_bars(
    ib, symbol: Symbol, *, duration: str = "5 D", bar_size: str = "1 day",
    what_to_show: str = "TRADES", use_rth: bool = True,
) -> list[dict]:
    contract = await qualify(ib, symbol)
    bars = await ib.reqHistoricalDataAsync(
        contract, endDateTime="", durationStr=duration, barSizeSetting=bar_size,
        whatToShow=what_to_show, useRTH=use_rth, formatDate=1,
    )
    return [
        {"date": str(b.date), "open": b.open, "high": b.high, "low": b.low,
         "close": b.close, "volume": float(b.volume)}
        for b in bars
    ]


async def get_option_chain(ib, symbol: Symbol) -> dict:
    contract = await qualify(ib, symbol)
    params = await ib.reqSecDefOptParamsAsync(contract.symbol, "", "STK", contract.conId)
    if not params:
        raise MarketDataNotEntitled(f"No option chain available for {symbol.code}.")
    chosen = next((p for p in params if p.exchange == "SMART"), params[0])
    return {
        "ticker": symbol.code, "exchange": chosen.exchange,
        "expirations": sorted(chosen.expirations), "strikes": sorted(chosen.strikes),
        "multiplier": chosen.multiplier,
    }
