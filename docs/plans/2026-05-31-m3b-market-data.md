# ibkr-mcp Milestone 3b — Market Data (quotes, bars, option chains)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. STRICT TDD.

**Goal:** Add the market-data read surface — `get_quote`, `get_historical_bars`, `get_option_chain` — as MCP read tools, entitlement-aware.

**Key design — delayed data is FREE:** default to `ib.reqMarketDataType(3)` (delayed), which IBKR provides with NO subscription. Real-time (type 1) needs a paid subscription. So `get_quote` is live-validatable for free (delayed). When NO data is available at all (all values `nan`), raise the M-errors `MarketDataNotEntitled`. The returned `market_data_type` tells the caller whether it got real-time (1) or delayed (3).

**Validation scope:** unit-tested with fakes. `get_quote` (delayed) is additionally live-validatable on the user's Gateway for free; bars/option-chain depend on the account's data permissions.

**Tech stack:** Python 3.11/3.12, `ib_async` (verified: `ib.reqMarketDataType(3)` delayed-free; `await ib.reqTickersAsync(contract)` → list[Ticker], fields `last/bid/ask/close/markPrice/marketDataType` default `nan`; `await ib.reqHistoricalDataAsync(contract, endDateTime, durationStr, barSizeSetting, whatToShow, useRTH, formatDate)` → list[BarData] date/open/high/low/close/volume; `await ib.reqSecDefOptParamsAsync(underlyingSymbol, futFopExchange, underlyingSecType, underlyingConId)` → list with .exchange/.expirations/.strikes/.multiplier; `qualify()` returns a Contract with `.conId` populated). Branch `m3b-marketdata`, `.venv/bin/...`, author Franck/franck@nganiet.fr, no AI mention.

---

### Task 1: `core/market_data.py`

**Files:** Create `ibkr_mcp/core/market_data.py`; Test `tests/test_market_data.py`.

- [ ] **Step 1 — failing test** `tests/test_market_data.py`:
```python
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
```

Run → FAIL (module missing).

- [ ] **Step 2 — implement** `ibkr_mcp/core/market_data.py`:
```python
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
```

Run → PASS. Commit: `git add ibkr_mcp/core/market_data.py tests/test_market_data.py && git commit -m "feat(core): market data reads (quote[delayed]/bars/option_chain), entitlement-aware (M3b)"`

---

### Task 2: MCP tools — get_quote / get_historical_bars / get_option_chain

**Files:** Modify `ibkr_mcp/mcp/tools_read.py`, `ibkr_mcp/mcp/server.py`; Test `tests/test_tools_read.py` (append).

These are READ tools — registered always (not gated by read_only).

- [ ] **Step 1 — failing test** append to `tests/test_tools_read.py`:
```python
async def test_quote_tool(monkeypatch):
    conn = _ReadsConn()
    conn._ib = object()

    async def fake_get_quote(ib, symbol, *, delayed=True):
        assert symbol.code == "AAPL"
        return {"ticker": "AAPL", "last": 150.5, "delayed": delayed}

    monkeypatch.setattr(tools_read, "get_quote", fake_get_quote)
    out = await tools_read.quote(conn, "aapl")
    assert conn.ensured is True
    assert out["ticker"] == "AAPL" and out["last"] == 150.5


async def test_historical_bars_tool(monkeypatch):
    conn = _ReadsConn()
    conn._ib = object()

    async def fake_bars(ib, symbol, **kw):
        return [{"date": "2026-05-31", "close": 2.0}]

    monkeypatch.setattr(tools_read, "get_historical_bars", fake_bars)
    out = await tools_read.historical_bars(conn, "AAPL", duration="1 D", bar_size="1 hour")
    assert out[0]["close"] == 2.0


async def test_option_chain_tool(monkeypatch):
    conn = _ReadsConn()
    conn._ib = object()

    async def fake_chain(ib, symbol):
        return {"ticker": "AAPL", "expirations": ["20260619"]}

    monkeypatch.setattr(tools_read, "get_option_chain", fake_chain)
    out = await tools_read.option_chain(conn, "AAPL")
    assert out["expirations"] == ["20260619"]
```

Run → FAIL.

- [ ] **Step 2 — append to** `ibkr_mcp/mcp/tools_read.py` (add imports at top: `from ibkr_mcp.core.market_data import get_historical_bars, get_option_chain, get_quote`; `from ibkr_mcp.core.models import Symbol`):
```python
async def quote(conn, ticker: str, *, delayed: bool = True) -> dict:
    await conn.ensure_connected()
    return await get_quote(conn.ib, Symbol.equity(ticker), delayed=delayed)


async def historical_bars(conn, ticker: str, *, duration: str = "5 D", bar_size: str = "1 day") -> list[dict]:
    await conn.ensure_connected()
    return await get_historical_bars(conn.ib, Symbol.equity(ticker), duration=duration, bar_size=bar_size)


async def option_chain(conn, ticker: str) -> dict:
    await conn.ensure_connected()
    return await get_option_chain(conn.ib, Symbol.equity(ticker))
```

- [ ] **Step 3 — register tools** in `ibkr_mcp/mcp/server.py` (in the read-tools section, alongside the existing reads):
```python
    @app.tool()
    async def get_quote(ticker: str, delayed: bool = True) -> dict:
        """Snapshot quote (last/bid/ask/close). Delayed by default (free); set delayed=false for real-time (needs a paid IBKR subscription)."""
        return await tools_read.quote(conn, ticker, delayed=delayed)

    @app.tool()
    async def get_historical_bars(ticker: str, duration: str = "5 D", bar_size: str = "1 day") -> list:
        """Historical OHLCV bars (e.g. duration='5 D', bar_size='1 day')."""
        return await tools_read.historical_bars(conn, ticker, duration=duration, bar_size=bar_size)

    @app.tool()
    async def get_option_chain(ticker: str) -> dict:
        """Option expirations and strikes for the underlying (SMART exchange)."""
        return await tools_read.option_chain(conn, ticker)
```

- [ ] **Step 4 — verify** `.venv/bin/pytest -v` (read tools tests pass; the existing `test_registered_tool_names` uses `<=` so it's unaffected; the 3 new read tools appear in both read-only and writable builds). Commit: `git add ibkr_mcp/mcp/tools_read.py ibkr_mcp/mcp/server.py tests/test_tools_read.py && git commit -m "feat(mcp): expose get_quote/get_historical_bars/get_option_chain tools (M3b)"`

---

## After all tasks
- `.venv/bin/pytest -v` → report totals (120 prior + ~10 new).
- `ruff check .` + `ruff format --check .` clean.
- Both architecture guards green (`market_data.py` imports ib_async-free? NO — it imports `qualify` from contracts which imports ib_async, and it's in `core/`, so it may reference ib_async indirectly; it must NOT import `mcp`/`fastmcp`. `tools_read.py` must NOT import `ib_async` — it imports `ibkr_mcp.core.market_data`).

## Self-review notes (author)
- §9 market-data tools (get_quote/get_historical_bars/get_option_chain) → Tasks 1-2; §11 entitlement degradation → delayed-default (free) + nan→None + MarketDataNotEntitled when no data; uses the M-errors type.
- Out of scope: per-position live valuation auto-enrichment (the LLM can `get_quote` a position's ticker and combine with `get_positions`); streaming/L2 depth; option greeks; real-time-vs-delayed per-field nuance.
- get_quote is live-validatable for FREE (delayed). This completes the read surface and the "go all" set (M3b + M4).
