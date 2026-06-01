import math

import pytest

from ibkr_mcp.core.errors import MarketDataNotEntitled
from ibkr_mcp.core.market_data import get_historical_bars, get_option_chain, get_quote
from ibkr_mcp.core.models import Symbol

NAN = float("nan")


class _Ticker:
    def __init__(self, last=NAN, bid=NAN, ask=NAN, close=NAN, mark=NAN, mdt=3):
        self.last, self.bid, self.ask, self.close, self.markPrice = last, bid, ask, close, mark
        self.marketDataType = mdt


class _Bar:
    def __init__(self, date, o, h, l, c, v):
        self.date, self.open, self.high, self.low, self.close, self.volume = date, o, h, l, c, v


class _OptParams:
    def __init__(self, exchange, expirations, strikes, multiplier="100"):
        self.exchange, self.expirations, self.strikes, self.multiplier = exchange, expirations, strikes, multiplier


class _Contract:
    def __init__(self, symbol="AAPL", con_id=1234):
        self.symbol, self.conId = symbol, con_id


class _MDIB:
    def __init__(self, ticker=None, bars=None, params=None):
        self._ticker, self._bars, self._params = ticker, bars or [], params or []
        self.md_type = None

    def reqMarketDataType(self, t):
        self.md_type = t

    async def qualifyContractsAsync(self, contract):
        return [_Contract()]

    async def reqTickersAsync(self, *contracts):
        return [self._ticker]

    async def reqHistoricalDataAsync(self, contract, **kw):
        return self._bars

    async def reqSecDefOptParamsAsync(self, sym, fut, sectype, conid):
        return self._params


async def test_get_quote_delayed_default():
    ib = _MDIB(ticker=_Ticker(last=150.5, bid=150.4, ask=150.6, close=149.0, mdt=3))
    out = await get_quote(ib, Symbol.equity("AAPL"))
    assert ib.md_type == 3  # delayed by default (free)
    assert out["last"] == 150.5 and out["bid"] == 150.4 and out["market_data_type"] == 3
    assert out["delayed"] is True


async def test_get_quote_realtime_when_requested():
    ib = _MDIB(ticker=_Ticker(last=150.5, mdt=1))
    out = await get_quote(ib, Symbol.equity("AAPL"), delayed=False)
    assert ib.md_type == 1


async def test_get_quote_nan_everything_raises_not_entitled():
    ib = _MDIB(ticker=_Ticker())  # all nan
    with pytest.raises(MarketDataNotEntitled):
        await get_quote(ib, Symbol.equity("ZZZZ"))


async def test_get_quote_nan_fields_become_none():
    ib = _MDIB(ticker=_Ticker(last=150.0))  # only last set; bid/ask/close/mark nan
    out = await get_quote(ib, Symbol.equity("AAPL"))
    assert out["last"] == 150.0 and out["bid"] is None and out["ask"] is None


async def test_get_historical_bars():
    ib = _MDIB(bars=[_Bar("2026-05-30", 1, 2, 0.5, 1.5, 1000), _Bar("2026-05-31", 1.5, 2.5, 1, 2, 2000)])
    out = await get_historical_bars(ib, Symbol.equity("AAPL"))
    assert len(out) == 2
    assert out[0] == {"date": "2026-05-30", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000.0}


async def test_get_option_chain_prefers_smart():
    ib = _MDIB(params=[
        _OptParams("CBOE", ["20260619"], [140.0, 150.0]),
        _OptParams("SMART", ["20260619", "20260717"], [150.0, 145.0]),
    ])
    out = await get_option_chain(ib, Symbol.equity("AAPL"))
    assert out["exchange"] == "SMART"
    assert out["expirations"] == ["20260619", "20260717"]  # sorted
    assert out["strikes"] == [145.0, 150.0]  # sorted


async def test_get_option_chain_empty_raises():
    ib = _MDIB(params=[])
    with pytest.raises(MarketDataNotEntitled):
        await get_option_chain(ib, Symbol.equity("ZZZZ"))
