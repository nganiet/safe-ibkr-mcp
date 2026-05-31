# ibkr-mcp Milestone 3a — Contracts + Free Account/Activity Reads

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. TDD mandatory — failing test first, with an injected fake IB (no Gateway needed for unit tests).

**Goal:** Add the no-entitlement read surface — positions, open orders, order status, executions — plus the `Symbol→Contract` translation they (and M4 writes) depend on. Exposed as MCP read tools.

**Architecture:** Extends `core/` (still `ib_async`-only, never `mcp`/FastMCP) and the thin `mcp/` tool layer. All data here is FREE (no IBKR market-data subscription): account/positions/orders/executions. Live price valuation of positions and all quotes/bars/option-chains are **M3b** (entitlement-gated) — explicitly out of scope here.

**Tech stack:** Python 3.11/3.12, `ib_async` (verified APIs: `ib.positions()`, `await ib.reqAllOpenOrdersAsync()`, `await ib.reqExecutionsAsync(filter)`, `await ib.qualifyContractsAsync(Stock(...))`). Tests use injected fakes via `.venv/bin/pytest`. Reference: design spec §7 (modules), §9 (tool table), §11 (entitlement boundary — note positions live-valuation is M3b).

## Working notes for the implementer

- Work in `/Users/fnganiet/projects/ibkr-mcp/` on branch `m3a-reads`. `cd` there each bash call. Use `.venv/bin/{pytest,ruff,python}`. Commit author Franck/franck@nganiet.fr, no AI mention.
- The domain dataclasses below are **copied verbatim from the Aegis `backend/app/brokers/base.py` shapes** (kept aligned for the future `ibkr-core`→adapter story). Do not rename fields.
- All new `core/` functions are `async def` for a uniform interface even when the underlying ib_async accessor is sync (`ib.positions()`), so the tool layer always `await`s them.
- `core/` must not import `mcp`/`fastmcp` (guarded). `mcp/tools_read.py` must not import `ib_async` (guarded).

---

### Task 1: extend `core/models.py` (Symbol, AssetClass, OrderStatus, PositionInfo, OrderUpdate)

**Files:** Modify `ibkr_mcp/core/models.py`; Test `tests/test_models.py` (append).

- [ ] **Step 1 — append failing tests** to `tests/test_models.py`:

```python
from decimal import Decimal

from ibkr_mcp.core.models import (
    AssetClass,
    OrderStatus,
    OrderUpdate,
    PositionInfo,
    Symbol,
)


def test_symbol_equity_shortcut():
    s = Symbol.equity("aapl")
    assert s.code == "AAPL"
    assert s.asset_class == AssetClass.EQUITY
    assert s.exchange is None


def test_order_status_values():
    assert OrderStatus.FILLED == "FILLED"
    assert OrderStatus.PARTIALLY_FILLED == "PARTIALLY_FILLED"


def test_position_info_fields():
    p = PositionInfo(
        ticker="AAPL", shares=Decimal(10), avg_cost=150.0,
        current_price=0.0, unrealized_pnl=0.0, market_value=0.0,
    )
    assert p.ticker == "AAPL"
    assert p.shares == Decimal(10)


def test_order_update_defaults():
    from datetime import datetime, timezone
    u = OrderUpdate(
        order_id="1", status=OrderStatus.SUBMITTED, filled_quantity=Decimal(0),
        fill_price=None, timestamp=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )
    assert u.broker_order_id is None
    assert u.raw == {}
```

Run `.venv/bin/pytest tests/test_models.py -v` → the 4 new ones FAIL (ImportError).

- [ ] **Step 2 — append to** `ibkr_mcp/core/models.py` (keep existing `BrokerHealth`/`AccountInfo`; add the enum/Decimal/field imports at top as needed):

```python
from dataclasses import dataclass, field   # update existing import line
from decimal import Decimal
from enum import Enum


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"
    CRYPTO = "CRYPTO"
    FUTURE = "FUTURE"
    FX = "FX"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class Symbol:
    code: str
    asset_class: AssetClass
    exchange: str | None = None

    @classmethod
    def equity(cls, ticker: str) -> "Symbol":
        return cls(code=ticker.upper(), asset_class=AssetClass.EQUITY)


@dataclass
class PositionInfo:
    ticker: str
    shares: Decimal
    avg_cost: float
    current_price: float
    unrealized_pnl: float
    market_value: float


@dataclass
class OrderUpdate:
    order_id: str
    status: OrderStatus
    filled_quantity: Decimal
    fill_price: float | None
    timestamp: datetime
    broker_order_id: str | None = None
    raw: dict = field(default_factory=dict)
```

(`datetime` is already imported in models.py from M1.) Run → PASS. Commit: `git add ibkr_mcp/core/models.py tests/test_models.py && git commit -m "feat(core): add Symbol/AssetClass/OrderStatus/PositionInfo/OrderUpdate models (M3a)"`

---

### Task 2: `core/contracts.py` — Symbol → ib_async Contract (equities)

**Files:** Create `ibkr_mcp/core/contracts.py`; Test `tests/test_contracts.py`.

- [ ] **Step 1 — failing test** `tests/test_contracts.py`:

```python
import pytest

from ibkr_mcp.core.contracts import qualify, to_ib_contract
from ibkr_mcp.core.models import AssetClass, Symbol


def test_to_ib_contract_equity_default_exchange():
    c = to_ib_contract(Symbol.equity("AAPL"))
    assert c.symbol == "AAPL"
    assert c.exchange == "SMART"
    assert c.currency == "USD"


def test_to_ib_contract_respects_explicit_exchange():
    c = to_ib_contract(Symbol(code="RY", asset_class=AssetClass.EQUITY, exchange="TSE"))
    assert c.exchange == "TSE"


def test_to_ib_contract_rejects_non_equity():
    with pytest.raises(ValueError, match="asset class"):
        to_ib_contract(Symbol(code="BTC", asset_class=AssetClass.CRYPTO))


class _FakeIB:
    def __init__(self, qualified):
        self._qualified = qualified
        self.qualified_with = None

    async def qualifyContractsAsync(self, contract):
        self.qualified_with = contract
        return self._qualified


async def test_qualify_returns_first_qualified():
    target = object()
    ib = _FakeIB([target])
    out = await qualify(ib, Symbol.equity("AAPL"))
    assert out is target


async def test_qualify_raises_when_unqualified():
    ib = _FakeIB([])
    with pytest.raises(ValueError, match="could not qualify"):
        await qualify(ib, Symbol.equity("ZZZZ"))
```

Run → FAIL (module missing).

- [ ] **Step 2 — implement** `ibkr_mcp/core/contracts.py`:

```python
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
        raise ValueError(f"Could not qualify contract for {symbol.code}.")
    return qualified[0]
```

Run → PASS. Commit: `git add ibkr_mcp/core/contracts.py tests/test_contracts.py && git commit -m "feat(core): add Symbol->Contract translation + qualify (equities) (M3a)"`

---

### Task 3: `core/account.py` — `get_positions`

**Files:** Modify `ibkr_mcp/core/account.py`; Test `tests/test_account.py` (append).

Positions come from `ib.positions()` (populated at connect). M3a returns shares + avg_cost; live valuation (`current_price`/`market_value`/`unrealized_pnl`) needs market data → **stays 0.0 in M3a**, enriched in M3b.

- [ ] **Step 1 — append failing test** to `tests/test_account.py`:

```python
from decimal import Decimal

from ibkr_mcp.core.account import get_positions


class _FakeContract:
    def __init__(self, symbol):
        self.symbol = symbol


class _FakePosition:
    def __init__(self, symbol, position, avg_cost):
        self.contract = _FakeContract(symbol)
        self.position = position
        self.avgCost = avg_cost


class _FakePosIB:
    def __init__(self, positions):
        self._positions = positions

    def positions(self):
        return self._positions


async def test_get_positions_maps_shares_and_cost():
    ib = _FakePosIB([_FakePosition("AAPL", 10, 150.0), _FakePosition("MSFT", 5, 300.0)])
    out = await get_positions(ib)
    assert [p.ticker for p in out] == ["AAPL", "MSFT"]
    assert out[0].shares == Decimal("10")
    assert out[0].avg_cost == 150.0
    # live valuation is M3b — unavailable fields are 0.0 in M3a
    assert out[0].current_price == 0.0
    assert out[0].market_value == 0.0
    assert out[0].unrealized_pnl == 0.0


async def test_get_positions_empty():
    assert await get_positions(_FakePosIB([])) == []
```

Run → FAIL.

- [ ] **Step 2 — append to** `ibkr_mcp/core/account.py`:

```python
from decimal import Decimal

from ibkr_mcp.core.models import PositionInfo


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
```

Run → PASS. Commit: `git add ibkr_mcp/core/account.py tests/test_account.py && git commit -m "feat(core): add get_positions (shares+cost; valuation deferred to M3b) (M3a)"`

---

### Task 4: `core/orders.py` — order/execution reads + status mapping

**Files:** Create `ibkr_mcp/core/orders.py`; Test `tests/test_orders_read.py`.

`get_open_orders` (from `reqAllOpenOrdersAsync`), `get_order_status(order_id)`, `get_executions(since)` (from `reqExecutionsAsync`). IBKR status strings map to our `OrderStatus`.

- [ ] **Step 1 — failing test** `tests/test_orders_read.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ibkr_mcp.core.models import OrderStatus
from ibkr_mcp.core.orders import (
    get_executions,
    get_open_orders,
    get_order_status,
    map_ib_status,
)


# --- status mapping ---

@pytest.mark.parametrize(
    "ib_status,filled,remaining,expected",
    [
        ("PendingSubmit", 0, 100, OrderStatus.PENDING),
        ("PreSubmitted", 0, 100, OrderStatus.PENDING),
        ("Submitted", 0, 100, OrderStatus.SUBMITTED),
        ("Submitted", 40, 60, OrderStatus.PARTIALLY_FILLED),
        ("Filled", 100, 0, OrderStatus.FILLED),
        ("Cancelled", 0, 0, OrderStatus.CANCELLED),
        ("ApiCancelled", 0, 0, OrderStatus.CANCELLED),
        ("Inactive", 0, 0, OrderStatus.REJECTED),
    ],
)
def test_map_ib_status(ib_status, filled, remaining, expected):
    assert map_ib_status(ib_status, filled, remaining) == expected


# --- fakes ---

class _Order:
    def __init__(self, order_id, perm_id):
        self.orderId = order_id
        self.permId = perm_id


class _Status:
    def __init__(self, status, filled, remaining, avg):
        self.status = status
        self.filled = filled
        self.remaining = remaining
        self.avgFillPrice = avg


class _LogEntry:
    def __init__(self, time):
        self.time = time


class _Trade:
    def __init__(self, order_id, perm_id, status, filled, remaining, avg, ts):
        self.order = _Order(order_id, perm_id)
        self.orderStatus = _Status(status, filled, remaining, avg)
        self.log = [_LogEntry(ts)]


class _OrdersIB:
    def __init__(self, trades, fills=None):
        self._trades = trades
        self._fills = fills or []

    async def reqAllOpenOrdersAsync(self):
        return self._trades

    async def reqExecutionsAsync(self, execFilter=None):
        return self._fills


_TS = datetime(2026, 5, 31, 14, 30, tzinfo=timezone.utc)


async def test_get_open_orders_maps_to_updates():
    ib = _OrdersIB([_Trade(7, 900, "Submitted", 40, 60, 150.5, _TS)])
    out = await get_open_orders(ib)
    assert len(out) == 1
    u = out[0]
    assert u.order_id == "7"
    assert u.status == OrderStatus.PARTIALLY_FILLED
    assert u.filled_quantity == Decimal("40")
    assert u.fill_price == 150.5
    assert u.broker_order_id == "900"
    assert u.timestamp == _TS


async def test_get_order_status_found_and_not_found():
    ib = _OrdersIB([_Trade(7, 900, "Filled", 100, 0, 150.5, _TS)])
    assert await get_order_status(ib, "7") == OrderStatus.FILLED
    assert await get_order_status(ib, "900") == OrderStatus.FILLED  # by permId too
    with pytest.raises(ValueError, match="not found"):
        await get_order_status(ib, "404")


# executions

class _Exec:
    def __init__(self, exec_id, time, side, shares, price):
        self.execId = exec_id
        self.time = time
        self.side = side
        self.shares = shares
        self.price = price


class _Commission:
    def __init__(self, commission, realized):
        self.commission = commission
        self.realizedPNL = realized


class _Fill:
    def __init__(self, symbol, exec_id, time, side, shares, price, commission, realized):
        self.contract = type("C", (), {"symbol": symbol})()
        self.execution = _Exec(exec_id, time, side, shares, price)
        self.commissionReport = _Commission(commission, realized)
        self.time = time


async def test_get_executions_filters_by_since():
    old = datetime(2026, 5, 30, tzinfo=timezone.utc)
    new = datetime(2026, 5, 31, tzinfo=timezone.utc)
    ib = _OrdersIB([], fills=[
        _Fill("AAPL", "e1", old, "BOT", 10, 150.0, 1.0, 0.0),
        _Fill("AAPL", "e2", new, "BOT", 5, 151.0, 1.0, 0.0),
    ])
    out = await get_executions(ib, since=datetime(2026, 5, 31, tzinfo=timezone.utc))
    assert [u.order_id for u in out] == ["e2"]
    assert out[0].filled_quantity == Decimal("5")
    assert out[0].fill_price == 151.0
    assert out[0].status == OrderStatus.FILLED
```

Run → FAIL (module missing).

- [ ] **Step 2 — implement** `ibkr_mcp/core/orders.py`:

```python
"""Order & execution READS + IBKR status mapping. Imports ib_async data shapes only,
never mcp/FastMCP. Write operations (place/cancel/modify) are M4.
"""

from datetime import datetime
from decimal import Decimal

from ibkr_mcp.core.models import OrderStatus, OrderUpdate

_PENDING = {"PendingSubmit", "ApiPending", "PreSubmitted", "PendingCancel"}
_CANCELLED = {"Cancelled", "ApiCancelled"}


def map_ib_status(ib_status: str, filled: float, remaining: float) -> OrderStatus:
    if ib_status == "Filled":
        return OrderStatus.FILLED
    if ib_status in _CANCELLED:
        return OrderStatus.CANCELLED
    if ib_status == "Inactive":
        return OrderStatus.REJECTED
    if ib_status in _PENDING:
        return OrderStatus.PENDING
    # Submitted (or unknown active): partial if some filled while some remains.
    if filled and remaining:
        return OrderStatus.PARTIALLY_FILLED
    return OrderStatus.SUBMITTED


def _trade_to_update(t) -> OrderUpdate:
    st = t.orderStatus
    return OrderUpdate(
        order_id=str(t.order.orderId),
        status=map_ib_status(st.status, st.filled, st.remaining),
        filled_quantity=Decimal(str(st.filled)),
        fill_price=float(st.avgFillPrice) if st.avgFillPrice else None,
        timestamp=t.log[-1].time,
        broker_order_id=str(t.order.permId) if t.order.permId else None,
        raw={"ib_status": st.status},
    )


async def get_open_orders(ib) -> list[OrderUpdate]:
    return [_trade_to_update(t) for t in await ib.reqAllOpenOrdersAsync()]


async def get_order_status(ib, order_id: str) -> OrderStatus:
    for t in await ib.reqAllOpenOrdersAsync():
        if order_id in (str(t.order.orderId), str(t.order.permId)):
            return map_ib_status(t.orderStatus.status, t.orderStatus.filled, t.orderStatus.remaining)
    raise ValueError(f"Order {order_id} not found among open orders.")


async def get_executions(ib, since: datetime) -> list[OrderUpdate]:
    out = []
    for f in await ib.reqExecutionsAsync():
        if f.time < since:
            continue
        out.append(
            OrderUpdate(
                order_id=str(f.execution.execId),
                status=OrderStatus.FILLED,
                filled_quantity=Decimal(str(f.execution.shares)),
                fill_price=float(f.execution.price),
                timestamp=f.time,
                broker_order_id=None,
                raw={
                    "side": f.execution.side,
                    "commission": getattr(f.commissionReport, "commission", None),
                    "realized_pnl": getattr(f.commissionReport, "realizedPNL", None),
                },
            )
        )
    return out
```

Run → PASS. Commit: `git add ibkr_mcp/core/orders.py tests/test_orders_read.py && git commit -m "feat(core): add order/execution reads + IBKR status mapping (M3a)"`

---

### Task 5: MCP tools — positions, open orders, order status, executions

**Files:** Modify `ibkr_mcp/mcp/tools_read.py` and `ibkr_mcp/mcp/server.py`; Test `tests/test_tools_read.py` (append).

Tool-logic functions stay FastMCP-free (take a connection, return LLM-friendly dicts/lists); `server.py` adds thin `@app.tool()` wrappers. All call `await conn.ensure_connected()` first.

- [ ] **Step 1 — append failing tests** to `tests/test_tools_read.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from ibkr_mcp.core.models import OrderStatus, OrderUpdate, PositionInfo


class _ReadsConn:
    is_paper = True

    def __init__(self):
        self.ensured = False

    async def ensure_connected(self):
        self.ensured = True

    @property
    def ib(self):
        return self._ib


async def test_positions_tool():
    conn = _ReadsConn()
    # patch core call via the connection's ib + monkeypatch-free: use a fake that tools call
    conn._ib = type("IB", (), {"positions": lambda self: [
        type("P", (), {"contract": type("C", (), {"symbol": "AAPL"})(), "position": 10, "avgCost": 150.0})()
    ]})()
    out = await tools_read.positions(conn)
    assert conn.ensured is True
    assert out[0]["ticker"] == "AAPL"
    assert out[0]["shares"] == "10"          # Decimal serialized as str
    assert out[0]["valuation_available"] is False


async def test_open_orders_tool(monkeypatch):
    conn = _ReadsConn()
    updates = [OrderUpdate("7", OrderStatus.SUBMITTED, Decimal(0), None,
                           datetime(2026, 5, 31, tzinfo=timezone.utc), broker_order_id="900")]

    async def fake_get_open_orders(ib):
        return updates

    monkeypatch.setattr(tools_read, "get_open_orders", fake_get_open_orders)
    conn._ib = object()
    out = await tools_read.open_orders(conn)
    assert conn.ensured is True
    assert out[0]["order_id"] == "7"
    assert out[0]["status"] == "SUBMITTED"
    assert out[0]["broker_order_id"] == "900"


async def test_order_status_tool(monkeypatch):
    conn = _ReadsConn()

    async def fake_status(ib, order_id):
        return OrderStatus.FILLED

    monkeypatch.setattr(tools_read, "get_order_status", fake_status)
    conn._ib = object()
    out = await tools_read.order_status(conn, "7")
    assert out == {"order_id": "7", "status": "FILLED"}


async def test_executions_tool(monkeypatch):
    conn = _ReadsConn()
    upd = [OrderUpdate("e1", OrderStatus.FILLED, Decimal(5), 151.0,
                       datetime(2026, 5, 31, tzinfo=timezone.utc))]

    async def fake_execs(ib, since):
        return upd

    monkeypatch.setattr(tools_read, "get_executions", fake_execs)
    conn._ib = object()
    out = await tools_read.executions(conn, since_iso="2026-05-31T00:00:00+00:00")
    assert out[0]["order_id"] == "e1"
    assert out[0]["filled_quantity"] == "5"
```

Run → FAIL.

- [ ] **Step 2 — append to** `ibkr_mcp/mcp/tools_read.py`:

```python
from datetime import datetime

from ibkr_mcp.core.account import get_positions
from ibkr_mcp.core.models import OrderUpdate
from ibkr_mcp.core.orders import get_executions, get_open_orders, get_order_status


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
    return [_update_to_dict(u) for u in await get_executions(conn.ib, since)]
```

- [ ] **Step 3 — register tools** in `ibkr_mcp/mcp/server.py` (add inside `build_server`, after the existing two tools):

```python
    @app.tool()
    async def get_positions() -> list:
        """Open positions: ticker, shares, avg cost. (Live valuation requires market data — added later.)"""
        return await tools_read.positions(conn)

    @app.tool()
    async def get_open_orders() -> list:
        """Currently open orders with status and fill progress."""
        return await tools_read.open_orders(conn)

    @app.tool()
    async def get_order_status(order_id: str) -> dict:
        """Status of a single order by IBKR order id or perm id."""
        return await tools_read.order_status(conn, order_id)

    @app.tool()
    async def get_executions(since_iso: str) -> list:
        """Fills since an ISO-8601 timestamp (e.g. 2026-05-31T00:00:00+00:00)."""
        return await tools_read.executions(conn, since_iso)
```

- [ ] **Step 4 — verify** `.venv/bin/pytest tests/test_tools_read.py -v` → PASS; then `.venv/bin/pytest tests/test_server.py -v` → update `test_registered_tool_names` is NOT required (it asserts a subset with `<=`, so the 4 new names don't break it). Confirm all green.

- [ ] **Step 5 — commit:** `git add ibkr_mcp/mcp/tools_read.py ibkr_mcp/mcp/server.py tests/test_tools_read.py && git commit -m "feat(mcp): expose positions/open-orders/order-status/executions tools (M3a)"`

---

### Task 6: extend the gated paper integration test (optional live coverage)

**Files:** Modify `tests/test_integration_paper.py`.

- [ ] **Step 1 — add** a gated test (runs only with `IBKR_MCP_RUN_INTEGRATION=1` + a paper Gateway). Append:

```python
@pytest.mark.skipif(not _RUN, reason="set IBKR_MCP_RUN_INTEGRATION=1 with a paper Gateway running")
async def test_reads_against_paper():
    conn = IBKRConnection("127.0.0.1", 4002, 98, readonly=True)
    try:
        await conn.ensure_connected()
        pos = await tools_read.positions(conn)
        assert isinstance(pos, list)  # may be empty on a fresh paper account
        oo = await tools_read.open_orders(conn)
        assert isinstance(oo, list)
        print("PAPER POSITIONS:", pos, "OPEN ORDERS:", oo)
    finally:
        conn.disconnect()
```

- [ ] **Step 2 — verify skip** `.venv/bin/pytest -v` → new test SKIPPED, all else green. Commit: `git add tests/test_integration_paper.py && git commit -m "test: gated paper reads integration (M3a)"`

---

## After all tasks

- `.venv/bin/pytest -v` → report totals (49 prior + ~4 models + ~5 contracts + ~2 positions + ~11 orders + ~4 tools = ~75 passed, 2 skipped — report actual).
- `.venv/bin/ruff check .` clean, `.venv/bin/ruff format --check .` clean (run `ruff format .` before each commit if needed).
- The architecture guard (`tests/test_architecture.py`) already covers the new `core/` files via `rglob`; confirm both guards still pass (core ↛ mcp, mcp ↛ ib_async). `tools_read.py` imports from `ibkr_mcp.core.*` only — NEVER `ib_async`.

## Self-review notes (author)

- **Spec coverage:** §9 read tools `get_positions`/`get_open_orders`/`get_order_status`/`get_executions` → Tasks 3-5; `core/contracts` (equities) → Task 2; domain shapes → Task 1. §11 boundary respected — positions live-valuation + all quotes/bars/option-chains deferred to **M3b** (documented in code).
- **Out of scope (M3b):** `core/market_data.py`, option-chain resolution, `core/errors.py` + entitlement (354/10089) degradation, live position valuation, `get_quote`/`get_historical_bars`/`get_option_chain`.
- **No placeholders. Fakes injected; no Gateway needed for unit tests. ib_async APIs verified via context7.**
