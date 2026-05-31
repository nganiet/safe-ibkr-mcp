# ibkr-mcp Milestone 4 — Write Tools (preview → confirm)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. STRICT TDD. This is MONEY-CRITICAL code (real fills). Implement exactly; the refusal path is built and proven FIRST.

**Goal:** Expose guarded order placement — `preview_order`, `confirm_order`, `cancel_order` — wiring the M2 safety primitives (GuardrailPolicy, KillSwitch, IdempotencyStore, PreviewTokenStore) into the actual IB order path. This is the project's differentiator: "the IBKR MCP you can hand an LLM without it emptying the account."

**⚠️ Validation scope:** M4 ships **fake-validated only**. Live-write validation is intentionally NOT done (paper 4002 is behind the gnzsnz modal; live writes are not acceptable for testing). "M4 done" = unit-tested with fakes + reviewed, NOT "placed a real order."

## Non-negotiable safety invariants (the whole point of M4)

1. **`read_only=True` ⇒ write tools are NEVER registered** (gate by construction, not a runtime check). The live `.mcp.json` runs `IBKR_READ_ONLY=true`, so the live server is write-less by construction. Test: `build_server` with a read-only config exposes ZERO write tools.
2. **Refuse-to-start belt-and-suspenders:** a WRITABLE server (`read_only=False`) pointed at a LIVE port (4001/7496) WITHOUT `IBKR_ALLOW_LIVE=true` refuses to start. (A read-only server on a live port is fine — that is the current validated setup, so the refusal applies ONLY when writes are enabled.)
3. **Order-time live gate:** `GuardrailPolicy.check_order` (built from config) rejects live orders unless `allow_live`, at BOTH preview and confirm.
4. **`confirm_order` ordering (money-correctness):** idempotency lookup on `client_order_id` comes BEFORE token consumption, so a retried confirm (lost response) returns the cached result instead of `UnknownToken` or a double-fill.
5. **The token carries the full order payload** (not just a hash): `confirm_order(confirm_token, client_order_id)` — the order spec comes from the token, so confirm cannot place different params than were previewed.

**Tech stack:** Python 3.11/3.12, `ib_async` (verified: `ib.placeOrder(contract, order)` → returns `Trade` immediately, non-blocking, fill via events → `confirm_order` returns SUBMITTED + permId; `ib.whatIfOrderAsync(contract, order)` → margin/commission; `ib.cancelOrder(order)`; `MarketOrder(action, qty)`, `LimitOrder(action, qty, lmtPrice)`, `StopOrder(action, qty, stopPrice)`). Branch `m4-write-tools`, `.venv/bin/...`, author Franck/franck@nganiet.fr, no AI mention.

---

### Task 1: models + config (+ refuse-to-start). Built FIRST — no placement possible yet.

**Files:** Modify `ibkr_mcp/core/models.py`, `ibkr_mcp/mcp/config.py`; Tests `tests/test_models.py`, `tests/test_config.py` (append).

- [ ] **Step 1 — append failing tests.**

`tests/test_models.py`:
```python
from ibkr_mcp.core.models import OrderConfirmation, OrderRequest, OrderSide, OrderType, Symbol
from decimal import Decimal
from ibkr_mcp.core.models import OrderStatus


def test_order_request_ticker_shortcut():
    r = OrderRequest(symbol=Symbol.equity("AAPL"), side=OrderSide.BUY,
                     order_type=OrderType.MARKET, quantity=Decimal(10))
    assert r.ticker == "AAPL"
    assert r.limit_price is None and r.stop_price is None


def test_order_confirmation_defaults():
    c = OrderConfirmation(order_id="1", status=OrderStatus.SUBMITTED)
    assert c.broker_order_id is None and c.reject_reason is None
    assert c.filled_quantity == Decimal(0)
```

`tests/test_config.py`:
```python
import pytest
from decimal import Decimal
from ibkr_mcp.mcp.config import Config


def test_write_config_defaults():
    c = Config.from_env({})
    assert c.allow_live is False
    assert c.max_order_qty is None
    assert c.max_order_notional_usd is None
    assert c.ticker_allowlist is None


def test_write_config_parsing():
    c = Config.from_env({
        "IBKR_ALLOW_LIVE": "true", "IBKR_MAX_ORDER_QTY": "100",
        "IBKR_MAX_ORDER_NOTIONAL_USD": "5000", "IBKR_TICKER_ALLOWLIST": "AAPL, MSFT",
    })
    assert c.allow_live is True
    assert c.max_order_qty == Decimal("100")
    assert c.max_order_notional_usd == 5000.0
    assert c.ticker_allowlist == frozenset({"AAPL", "MSFT"})


def test_validate_refuses_writable_live_without_optin():
    # writable (read_only False) + live port + not allow_live → refuse
    cfg = Config(port=4001, read_only=False, allow_live=False)
    with pytest.raises(ValueError, match="live"):
        cfg.validate()


def test_validate_allows_readonly_on_live_port():
    Config(port=4001, read_only=True, allow_live=False).validate()  # must NOT raise


def test_validate_allows_writable_live_with_optin():
    Config(port=4001, read_only=False, allow_live=True).validate()  # must NOT raise


def test_validate_allows_writable_paper():
    Config(port=4002, read_only=False, allow_live=False).validate()  # paper port, fine
```

Run both → new tests FAIL.

- [ ] **Step 2 — implement.** Append to `ibkr_mcp/core/models.py`:
```python
class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


@dataclass
class OrderRequest:
    symbol: Symbol
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "DAY"

    @property
    def ticker(self) -> str:
        return self.symbol.code


@dataclass
class OrderConfirmation:
    order_id: str
    status: OrderStatus
    fill_price: float | None = None
    filled_quantity: Decimal = field(default_factory=lambda: Decimal(0))
    timestamp: datetime | None = None
    broker_order_id: str | None = None
    reject_reason: str | None = None
```

Modify `ibkr_mcp/mcp/config.py` — add imports (`from dataclasses import dataclass, field`, `from decimal import Decimal`, `from pathlib import Path`), the module constant, and fields:
```python
_LIVE_PORTS = {4001, 7496}


# add fields to the Config dataclass:
    allow_live: bool = False
    max_order_qty: Decimal | None = None
    max_order_notional_usd: float | None = None
    ticker_allowlist: frozenset[str] | None = None
    state_dir: Path = field(default_factory=lambda: Path.home() / ".ibkr-mcp")
```
Extend `from_env` to read them (incl. `IBKR_STATE_DIR` so tests never touch the real home):
```python
        qty = env.get("IBKR_MAX_ORDER_QTY")
        notional = env.get("IBKR_MAX_ORDER_NOTIONAL_USD")
        allowlist = env.get("IBKR_TICKER_ALLOWLIST")
        state_dir = env.get("IBKR_STATE_DIR")
        return cls(
            host=env.get("IBKR_HOST", "127.0.0.1"),
            port=int(env.get("IBKR_PORT", "4002")),
            client_id=int(env.get("IBKR_CLIENT_ID", "1")),
            read_only=env.get("IBKR_READ_ONLY", "true").strip().lower() in _TRUTHY,
            allow_live=env.get("IBKR_ALLOW_LIVE", "false").strip().lower() in _TRUTHY,
            max_order_qty=Decimal(qty) if qty else None,
            max_order_notional_usd=float(notional) if notional else None,
            ticker_allowlist=(
                frozenset(t.strip().upper() for t in allowlist.split(",") if t.strip())
                if allowlist else None
            ),
            state_dir=Path(state_dir) if state_dir else (Path.home() / ".ibkr-mcp"),
        )
```
(The two existing M1 config tests assert the read fields; they keep passing — only NEW fields are added with defaults.)
Add a method:
```python
    def validate(self) -> None:
        """Refuse a writable server pointed at a live port without explicit opt-in."""
        if not self.read_only and not self.allow_live and self.port in _LIVE_PORTS:
            raise ValueError(
                f"Refusing to start: writable server on live port {self.port} without "
                "IBKR_ALLOW_LIVE=true. Set IBKR_READ_ONLY=true, use a paper port (4002), "
                "or set IBKR_ALLOW_LIVE=true to trade live deliberately."
            )
```

Run → PASS. Commit: `git add ibkr_mcp/core/models.py ibkr_mcp/mcp/config.py tests/test_models.py tests/test_config.py && git commit -m "feat(m4): OrderRequest/OrderConfirmation models + write config + refuse-to-start gate"`

---

### Task 2: PreviewTokenStore carries the order payload

**Files:** Modify `ibkr_mcp/core/safety/idempotency.py`; Test `tests/test_idempotency.py` (amend the PreviewTokenStore tests).

M2's token stored a `params_hash`; M4 needs the token to carry the full order spec so `confirm_order` places exactly what was previewed without re-sending params.

- [ ] **Step 1 — amend the PreviewTokenStore tests** in `tests/test_idempotency.py`. Replace every `issue("hash-...")` / `consume(token, "hash-...")` usage with the payload API below, and DROP the `ParamsMismatch` test (no longer applicable — there is no separate hash to mismatch). Keep the expiry + single-use + unknown-token tests, adapted:
```python
def test_issue_then_consume_returns_payload(tmp_path):
    clock = _Clock(datetime(2026, 5, 31, tzinfo=timezone.utc))
    s = PreviewTokenStore(db_path=tmp_path / "state.db", now=clock)
    tok = s.issue({"symbol": "AAPL", "side": "BUY", "qty": "10"})
    assert isinstance(tok, str) and len(tok) >= 16
    assert s.consume(tok) == {"symbol": "AAPL", "side": "BUY", "qty": "10"}


def test_consume_is_single_use(tmp_path):
    clock = _Clock(datetime(2026, 5, 31, tzinfo=timezone.utc))
    s = PreviewTokenStore(db_path=tmp_path / "state.db", now=clock)
    tok = s.issue({"a": 1})
    s.consume(tok)
    with pytest.raises(UnknownToken):
        s.consume(tok)


def test_expired_token_rejected_and_burned(tmp_path):
    clock = _Clock(datetime(2026, 5, 31, tzinfo=timezone.utc))
    s = PreviewTokenStore(db_path=tmp_path / "state.db", now=clock)
    tok = s.issue({"a": 1})
    clock.advance(61)
    with pytest.raises(ExpiredToken):
        s.consume(tok, ttl_seconds=60)
    with pytest.raises(UnknownToken):  # burned even on expiry
        s.consume(tok)


def test_unknown_token_rejected(tmp_path):
    s = PreviewTokenStore(db_path=tmp_path / "state.db")
    with pytest.raises(UnknownToken):
        s.consume("never-issued")
```
Remove the `ParamsMismatch` import and `test_params_mismatch_*` / `test_token_gone_after_params_mismatch` tests. Keep `test_token_gone_after_expired_consume` only if it matches the new signature (else fold into `test_expired_token_rejected_and_burned`).

Run → the amended tests FAIL (old `issue`/`consume` signature).

- [ ] **Step 2 — modify `PreviewTokenStore`** in `ibkr_mcp/core/safety/idempotency.py`. Drop `ParamsMismatch`. New schema column `payload` (JSON) instead of `params_hash`:
```python
class PreviewTokenStore:
    def __init__(self, db_path=None, *, now=None):
        self._db = db_path if db_path is not None else _DEFAULT_DB
        self._now = now if now is not None else (lambda: datetime.now(timezone.utc))
        with contextlib.closing(_connect(self._db)) as c, c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS preview_tokens "
                "(token TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)"
            )

    def issue(self, payload: dict) -> str:
        token = secrets.token_urlsafe(24)
        with contextlib.closing(_connect(self._db)) as c, c:
            c.execute(
                "INSERT INTO preview_tokens (token, payload, created_at) VALUES (?, ?, ?)",
                (token, json.dumps(payload), self._now().isoformat()),
            )
        return token

    def consume(self, token: str, *, ttl_seconds: int = 60) -> dict:
        with contextlib.closing(_connect(self._db)) as c, c:
            row = c.execute(
                "SELECT payload, created_at FROM preview_tokens WHERE token = ?", (token,)
            ).fetchone()
            if row is None:
                raise UnknownToken("Preview token not found or already consumed.")
            payload, created_at = json.loads(row[0]), datetime.fromisoformat(row[1])
            c.execute("DELETE FROM preview_tokens WHERE token = ?", (token,))
        if (self._now() - created_at).total_seconds() > ttl_seconds:
            raise ExpiredToken("Preview token has expired — re-run preview_order.")
        return payload
```
Delete the `ParamsMismatch` class and its export. Keep `UnknownToken`, `ExpiredToken`, `IdempotencyStore` unchanged.

Run → PASS. Commit: `git add ibkr_mcp/core/safety/idempotency.py tests/test_idempotency.py && git commit -m "refactor(safety): PreviewTokenStore carries the order payload (M4 needs it)"`

---

### Task 3: `core/orders.py` write functions (real IB calls, fake-tested)

**Files:** Modify `ibkr_mcp/core/orders.py`; Test `tests/test_orders_write.py`.

- [ ] **Step 1 — failing test** `tests/test_orders_write.py`:
```python
from decimal import Decimal

import pytest

from ibkr_mcp.core.models import OrderConfirmation, OrderRequest, OrderSide, OrderStatus, OrderType, Symbol
from ibkr_mcp.core.orders import build_ib_order, cancel_order, place_order, what_if


def _req(order_type=OrderType.LIMIT, qty=10, limit=150.0, stop=None, side=OrderSide.BUY):
    return OrderRequest(symbol=Symbol.equity("AAPL"), side=side, order_type=order_type,
                        quantity=Decimal(qty), limit_price=limit, stop_price=stop)


def test_build_ib_order_limit():
    o = build_ib_order(_req(OrderType.LIMIT, 10, 150.0))
    assert o.action == "BUY" and o.totalQuantity == 10 and o.lmtPrice == 150.0
    assert o.orderType == "LMT"


def test_build_ib_order_market():
    o = build_ib_order(_req(OrderType.MARKET, 5, None, side=OrderSide.SELL))
    assert o.action == "SELL" and o.totalQuantity == 5 and o.orderType == "MKT"


def test_build_ib_order_stop():
    o = build_ib_order(_req(OrderType.STOP, 5, None, stop=140.0))
    assert o.orderType == "STP" and o.auxPrice == 140.0


def test_build_ib_order_limit_requires_price():
    with pytest.raises(ValueError, match="limit_price"):
        build_ib_order(_req(OrderType.LIMIT, 10, None))


class _Trade:
    def __init__(self):
        self.order = type("O", (), {"permId": 555})()
        self.orderStatus = type("S", (), {"status": "Submitted", "filled": 0, "remaining": 10, "avgFillPrice": 0.0})()


class _PlaceIB:
    def __init__(self):
        self.placed = None

    async def qualifyContractsAsync(self, contract):
        return [contract]

    def placeOrder(self, contract, order):
        self.placed = (contract, order)
        return _Trade()

    async def whatIfOrderAsync(self, contract, order):
        return type("OS", (), {"initMarginChange": "1500", "commission": 1.0,
                               "maxCommission": 1.0, "minCommission": 1.0})()


async def test_place_order_returns_submitted_confirmation():
    ib = _PlaceIB()
    conf = await place_order(ib, _req())
    assert isinstance(conf, OrderConfirmation)
    assert conf.status == OrderStatus.SUBMITTED
    assert conf.broker_order_id == "555"
    assert ib.placed is not None  # actually called placeOrder


async def test_what_if_returns_margin_commission():
    ib = _PlaceIB()
    out = await what_if(ib, _req())
    assert "init_margin_change" in out
    assert out["commission"] == 1.0
```

(For `cancel_order`, append a fake with an open trade and assert it calls `cancelOrder`; mirror the read-side `_OrdersIB` pattern. Keep it minimal.)

Run → FAIL.

- [ ] **Step 2 — implement.** Append to `ibkr_mcp/core/orders.py` (top imports add: `from ib_async import LimitOrder, MarketOrder, StopOrder`; `from ibkr_mcp.core.contracts import qualify`; `from ibkr_mcp.core.models import OrderConfirmation, OrderRequest, OrderType`):
```python
def build_ib_order(req: OrderRequest):
    action = req.side.value  # "BUY" / "SELL"
    qty = float(req.quantity)
    if req.order_type == OrderType.MARKET:
        return MarketOrder(action, qty)
    if req.order_type == OrderType.LIMIT:
        if req.limit_price is None:
            raise ValueError("limit_price is required for a LIMIT order")
        return LimitOrder(action, qty, req.limit_price)
    if req.order_type == OrderType.STOP:
        if req.stop_price is None:
            raise ValueError("stop_price is required for a STOP order")
        return StopOrder(action, qty, req.stop_price)
    raise ValueError(f"Unsupported order type: {req.order_type}")


async def what_if(ib, req: OrderRequest) -> dict:
    contract = await qualify(ib, req.symbol)
    state = await ib.whatIfOrderAsync(contract, build_ib_order(req))
    return {
        "init_margin_change": getattr(state, "initMarginChange", None),
        "maint_margin_change": getattr(state, "maintMarginChange", None),
        "commission": getattr(state, "commission", None),
        "max_commission": getattr(state, "maxCommission", None),
        "warning": getattr(state, "warningText", None),
    }


async def place_order(ib, req: OrderRequest) -> OrderConfirmation:
    contract = await qualify(ib, req.symbol)
    trade = ib.placeOrder(contract, build_ib_order(req))  # non-blocking; fill via events
    st = trade.orderStatus
    return OrderConfirmation(
        order_id=str(getattr(trade.order, "permId", "") or ""),
        status=map_ib_status(st.status, st.filled, st.remaining),
        filled_quantity=Decimal(str(st.filled)),
        fill_price=float(st.avgFillPrice) if st.avgFillPrice else None,
        broker_order_id=str(trade.order.permId) if trade.order.permId else None,
    )


async def cancel_order(ib, order_id: str) -> OrderConfirmation:
    for t in await ib.reqAllOpenOrdersAsync():
        if order_id in (str(t.order.orderId), str(t.order.permId)):
            ib.cancelOrder(t.order)
            return OrderConfirmation(
                order_id=order_id, status=OrderStatus.CANCELLED,
                broker_order_id=str(t.order.permId) if t.order.permId else None,
            )
    raise ValueError(f"Order {order_id} not found among open orders.")
```

Run → PASS. Commit: `git add ibkr_mcp/core/orders.py tests/test_orders_write.py && git commit -m "feat(core): order write functions (build/what_if/place/cancel) (M4)"`

---

### Task 4: `mcp/tools_write.py` — preview → confirm orchestration (the safety wiring)

**Files:** Create `ibkr_mcp/mcp/tools_write.py`; Test `tests/test_tools_write.py`.

This is the money-critical orchestration. `preview_order` runs guardrails + whatIf and issues a payload-bearing token. `confirm_order` does **idempotency-first**, then token-consume, killswitch, guardrails, place, remember.

- [ ] **Step 1 — failing test** `tests/test_tools_write.py`:
```python
from decimal import Decimal

import pytest

from ibkr_mcp.core.models import OrderConfirmation, OrderStatus
from ibkr_mcp.core.safety.guardrails import GuardrailPolicy, GuardrailViolation
from ibkr_mcp.core.safety.idempotency import IdempotencyStore, PreviewTokenStore
from ibkr_mcp.core.safety.killswitch import KillSwitch, KillSwitchEngaged
from ibkr_mcp.mcp import tools_write


class _Conn:
    def __init__(self, is_paper=True):
        self.is_paper = is_paper
        self.ensured = False
        self.ib = object()

    async def ensure_connected(self):
        self.ensured = True


def _ctx(tmp_path, policy=None, killswitch=None):
    return tools_write.WriteContext(
        policy=policy or GuardrailPolicy(),
        killswitch=killswitch or KillSwitch(path=tmp_path / "KILL"),
        idempotency=IdempotencyStore(db_path=tmp_path / "state.db"),
        tokens=PreviewTokenStore(db_path=tmp_path / "state.db"),
    )


_ORDER = {"symbol": "AAPL", "side": "BUY", "order_type": "LIMIT", "quantity": "10", "limit_price": 150.0}


async def test_preview_rejected_by_guardrail_before_token(tmp_path, monkeypatch):
    # qty cap exceeded → preview must raise, issue NO token
    ctx = _ctx(tmp_path, policy=GuardrailPolicy(max_order_qty=Decimal(5)))
    monkeypatch.setattr(tools_write, "what_if", _fail_if_called)
    with pytest.raises(GuardrailViolation):
        await tools_write.preview_order(_Conn(), ctx, **_ORDER)


async def test_preview_then_confirm_places_once(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(tools_write, "what_if", _fake_what_if)
    placements = []

    async def fake_place(ib, req):
        placements.append(req.ticker)
        return OrderConfirmation(order_id="555", status=OrderStatus.SUBMITTED, broker_order_id="555")

    monkeypatch.setattr(tools_write, "place_order", fake_place)

    prev = await tools_write.preview_order(_Conn(), ctx, **_ORDER)
    assert "confirm_token" in prev and prev["confirm_token"]

    conf1 = await tools_write.confirm_order(_Conn(), ctx, confirm_token=prev["confirm_token"], client_order_id="cli-1")
    assert conf1["status"] == "SUBMITTED"
    # MONEY-CRITICAL retry: same client_order_id → cached result, NO second placement, NO UnknownToken
    conf2 = await tools_write.confirm_order(_Conn(), ctx, confirm_token=prev["confirm_token"], client_order_id="cli-1")
    assert conf2 == conf1
    assert placements == ["AAPL"]  # placed exactly once


async def test_confirm_blocked_by_killswitch(tmp_path, monkeypatch):
    ks = KillSwitch(path=tmp_path / "KILL")
    ks.arm("freeze")
    ctx = _ctx(tmp_path, killswitch=ks)
    monkeypatch.setattr(tools_write, "what_if", _fake_what_if)
    monkeypatch.setattr(tools_write, "place_order", _fail_if_called)
    # token issued via a non-armed preview path: issue directly
    tok = ctx.tokens.issue(_ORDER)
    with pytest.raises(KillSwitchEngaged):
        await tools_write.confirm_order(_Conn(), ctx, confirm_token=tok, client_order_id="cli-2")


async def test_confirm_live_blocked_without_optin(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, policy=GuardrailPolicy(allow_live=False))
    monkeypatch.setattr(tools_write, "place_order", _fail_if_called)
    tok = ctx.tokens.issue(_ORDER)
    with pytest.raises(GuardrailViolation) as e:
        await tools_write.confirm_order(_Conn(is_paper=False), ctx, confirm_token=tok, client_order_id="cli-3")
    assert e.value.code == "LIVE_NOT_ALLOWED"


async def _fake_what_if(ib, req):
    return {"init_margin_change": "1500", "commission": 1.0}


async def _fail_if_called(*a, **k):
    raise AssertionError("must not be called")
```

Run → FAIL.

- [ ] **Step 2 — implement** `ibkr_mcp/mcp/tools_write.py`:
```python
"""Write-tool orchestration — preview -> confirm. FastMCP-free for testability.

Wires the M2 safety primitives into the order path. NEVER imports ib_async
(goes through ibkr_mcp.core). The build_server layer registers these tools ONLY
when the server is writable (read_only=False).
"""

from dataclasses import dataclass
from decimal import Decimal

from ibkr_mcp.core.models import OrderRequest, OrderSide, OrderType, Symbol
from ibkr_mcp.core.orders import place_order, what_if
from ibkr_mcp.core.safety.guardrails import GuardrailPolicy
from ibkr_mcp.core.safety.idempotency import IdempotencyStore, PreviewTokenStore
from ibkr_mcp.core.safety.killswitch import KillSwitch


@dataclass
class WriteContext:
    policy: GuardrailPolicy
    killswitch: KillSwitch
    idempotency: IdempotencyStore
    tokens: PreviewTokenStore


def _req_from_payload(p: dict) -> OrderRequest:
    return OrderRequest(
        symbol=Symbol.equity(p["symbol"]),
        side=OrderSide(p["side"]),
        order_type=OrderType(p["order_type"]),
        quantity=Decimal(str(p["quantity"])),
        limit_price=p.get("limit_price"),
        stop_price=p.get("stop_price"),
    )


def _est_price(p: dict) -> float | None:
    # Notional cap needs a price; use the limit price when present (market orders
    # have no pre-trade price until M3b live quotes — notional check then skipped).
    return p.get("limit_price") or p.get("stop_price")


async def preview_order(conn, ctx: WriteContext, **payload) -> dict:
    await conn.ensure_connected()
    req = _req_from_payload(payload)
    # Guardrails BEFORE issuing a token — a capped/disallowed order never previews.
    ctx.policy.check_order(
        ticker=req.ticker, qty=req.quantity, est_price=_est_price(payload),
        is_paper=conn.is_paper,
    )
    impact = await what_if(conn.ib, req)
    token = ctx.tokens.issue(payload)
    return {"preview": {"order": payload, "impact": impact}, "confirm_token": token,
            "expires_in_seconds": 60}


async def confirm_order(conn, ctx: WriteContext, *, confirm_token: str, client_order_id: str) -> dict:
    await conn.ensure_connected()
    # (a) Idempotency FIRST — a retried confirm (lost response) returns the cached
    #     result without consuming the token or re-placing. Money-critical ordering.
    cached = ctx.idempotency.get(client_order_id)
    if cached is not None:
        return cached
    # (b) consume the single-use token → the exact previewed order payload.
    payload = ctx.tokens.consume(confirm_token)
    req = _req_from_payload(payload)
    # (c) re-check kill-switch + guardrails at confirm time (defense-in-depth).
    ctx.killswitch.check()
    ctx.policy.check_order(
        ticker=req.ticker, qty=req.quantity, est_price=_est_price(payload),
        is_paper=conn.is_paper,
    )
    # (d) place, (e) remember.
    conf = await place_order(conn.ib, req)
    result = {
        "order_id": conf.order_id, "status": conf.status.value,
        "broker_order_id": conf.broker_order_id, "client_order_id": client_order_id,
    }
    ctx.idempotency.remember(client_order_id, result)
    return result


async def cancel_order_tool(conn, ctx: WriteContext, *, order_id: str) -> dict:
    await conn.ensure_connected()
    ctx.killswitch.check()
    from ibkr_mcp.core.orders import cancel_order
    conf = await cancel_order(conn.ib, order_id)
    return {"order_id": conf.order_id, "status": conf.status.value,
            "broker_order_id": conf.broker_order_id}
```

Run → PASS. Commit: `git add ibkr_mcp/mcp/tools_write.py tests/test_tools_write.py && git commit -m "feat(mcp): preview->confirm write orchestration with safety wiring (M4)"`

---

### Task 5: register write tools ONLY when writable + wire config

**Files:** Modify `ibkr_mcp/mcp/server.py`, `ibkr_mcp/__main__.py`; Test `tests/test_server.py` (append).

- [ ] **Step 1 — failing test** `tests/test_server.py`:
```python
from ibkr_mcp.mcp.config import Config


async def test_readonly_config_registers_no_write_tools():
    app = build_server(_FakeConn(), Config(read_only=True))
    names = {t.name for t in await app.list_tools()}
    assert "preview_order" not in names and "confirm_order" not in names and "cancel_order" not in names
    assert {"ibkr_health", "get_account_summary"} <= names  # reads still there


async def test_writable_config_registers_write_tools(tmp_path):
    # state_dir=tmp_path so the writable build's stores never touch the real ~/.ibkr-mcp
    app = build_server(_FakeConn(), Config(read_only=False, port=4002, state_dir=tmp_path))
    names = {t.name for t in await app.list_tools()}
    assert {"preview_order", "confirm_order", "cancel_order"} <= names
```
(Existing `test_build_server_returns_fastmcp_without_connecting` and `test_registered_tool_names` must keep passing — `build_server` keeps working with a default/read-only config.)

Run → FAIL.

- [ ] **Step 2 — modify `build_server`** in `ibkr_mcp/mcp/server.py` to take an optional config and register write tools only when writable:
```python
from ibkr_mcp.mcp.config import Config
from ibkr_mcp.mcp import tools_write
from ibkr_mcp.core.safety.guardrails import GuardrailPolicy
from ibkr_mcp.core.safety.idempotency import IdempotencyStore, PreviewTokenStore
from ibkr_mcp.core.safety.killswitch import KillSwitch


def build_server(conn, config: Config | None = None) -> FastMCP:
    config = config if config is not None else Config()  # default: read-only
    app = FastMCP("ibkr-mcp", instructions=(
        "Guarded Interactive Brokers access. Paper-trading by default. "
        + ("Read-only build." if config.read_only else "Writable build — orders go through preview_order then confirm_order.")
    ))
    # ... existing read tools (ibkr_health, get_account_summary, get_positions,
    #     get_open_orders, get_order_status, get_executions) unchanged ...

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
        async def preview_order(symbol: str, side: str, order_type: str, quantity: str,
                                limit_price: float | None = None, stop_price: float | None = None) -> dict:
            """Validate an order against guardrails, compute margin/commission, and return a single-use confirm_token. Places NOTHING."""
            return await tools_write.preview_order(
                conn, ctx, symbol=symbol, side=side, order_type=order_type,
                quantity=quantity, limit_price=limit_price, stop_price=stop_price)

        @app.tool()
        async def confirm_order(confirm_token: str, client_order_id: str) -> dict:
            """Place the order previewed under confirm_token. Idempotent on client_order_id (safe to retry)."""
            return await tools_write.confirm_order(
                conn, ctx, confirm_token=confirm_token, client_order_id=client_order_id)

        @app.tool()
        async def cancel_order(order_id: str) -> dict:
            """Cancel an open order by IBKR order id or perm id."""
            return await tools_write.cancel_order_tool(conn, ctx, order_id=order_id)

    return app
```
Modify `ibkr_mcp/__main__.py` to validate + pass config:
```python
def main() -> None:
    config = Config.from_env()
    config.validate()  # refuse writable server on a live port without opt-in
    conn = IBKRConnection(config.host, config.port, config.client_id, readonly=config.read_only)
    app = build_server(conn, config)
    try:
        app.run()
    finally:
        conn.disconnect()
```

Run → PASS. Commit: `git add ibkr_mcp/mcp/server.py ibkr_mcp/__main__.py tests/test_server.py && git commit -m "feat(mcp): register write tools only when writable + validate config at startup (M4)"`

---

## After all tasks

- `.venv/bin/pytest -v` → report totals (97 prior + write tests; ~115+ passed, 2 skipped — report actual).
- `.venv/bin/ruff check .` + `.venv/bin/ruff format --check .` clean.
- BOTH architecture guards green (`core/` ↛ mcp; `mcp/tools_write.py` ↛ ib_async — it goes through `ibkr_mcp.core`).
- **Manually confirm the headline invariant:** the test `test_readonly_config_registers_no_write_tools` proves the live read-only `.mcp.json` setup can never expose a write tool.

## Self-review notes (author)
- Invariant 1 (read_only ⇒ no write tools) → Task 5 test. Invariant 2 (refuse writable+live+no-optin) → Task 1 `validate` + `__main__`. Invariant 3 (order-time live gate) → Task 4 `test_confirm_live_blocked_without_optin`. Invariant 4 (idempotency-before-token) → Task 4 `test_preview_then_confirm_places_once` retry assertion. Invariant 5 (token carries payload) → Task 2.
- Guardrails run at preview (Task 4 `preview_order`) AND confirm (Task 4 `confirm_order`) — defense-in-depth.
- **Live-write validation deliberately deferred** — fake-validated only (paper behind modal; live writes not test-acceptable). Done ≠ real order placed.
- Out of scope: market-order notional cap needs a live price (M3b); bracket/OCA/trailing orders; modify_order (cancel+re-preview suffices for now).
