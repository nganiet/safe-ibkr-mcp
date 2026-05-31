# ibkr-mcp Milestone E — Error Mapping (§13)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Strict TDD.

**Goal:** Typed IBKR error domain + classifiers, and wire connect-failures into a clean `BrokerUnavailable` so tools stop surfacing raw `[Errno 61]`. Pulled out of M3b because M4 (`confirm_order` rejections) depends on these types.

**Architecture:** New `core/errors.py` (pure stdlib — no `ib_async`, no `mcp`). `core/connection.py` wraps `connectAsync` failures. The MCP tool layer lets exceptions propagate — FastMCP serializes `str(exc)` to the client, so each error carries an actionable message.

**Tech stack:** Python 3.11/3.12 stdlib only. Branch `errors-mapping`, `.venv/bin/...`, author Franck/franck@nganiet.fr, no AI mention.

---

### Task 1: `core/errors.py` — typed errors + classifiers

**Files:** Create `ibkr_mcp/core/errors.py`; Test `tests/test_errors.py`.

- [ ] **Step 1 — failing test** `tests/test_errors.py`:

```python
import pytest

from ibkr_mcp.core.errors import (
    BrokerUnavailable,
    ContractNotFound,
    IBKRError,
    MarketDataNotEntitled,
    OrderRejected,
    broker_unavailable_from_connect,
    classify_ib_error,
)


def test_error_codes():
    assert IBKRError.code == "IBKR_ERROR"
    assert BrokerUnavailable.code == "BROKER_UNAVAILABLE"
    assert MarketDataNotEntitled.code == "MARKET_DATA_NOT_ENTITLED"
    assert OrderRejected.code == "ORDER_REJECTED"
    assert ContractNotFound.code == "CONTRACT_NOT_FOUND"
    assert issubclass(BrokerUnavailable, IBKRError)


def test_str_is_the_message():
    e = BrokerUnavailable("gateway down")
    assert str(e) == "gateway down"
    assert e.code == "BROKER_UNAVAILABLE"


def test_broker_unavailable_from_connect_refused():
    e = broker_unavailable_from_connect(ConnectionRefusedError(61, "refused"), "127.0.0.1", 4001)
    assert isinstance(e, BrokerUnavailable)
    assert "127.0.0.1:4001" in str(e)
    assert "running" in str(e).lower()  # actionable hint


def test_broker_unavailable_from_connect_timeout():
    e = broker_unavailable_from_connect(TimeoutError(), "127.0.0.1", 4001)
    assert isinstance(e, BrokerUnavailable)
    assert "handshake" in str(e).lower()  # the modal/api-not-enabled case


@pytest.mark.parametrize(
    "code,expected",
    [
        (354, MarketDataNotEntitled),
        (10089, MarketDataNotEntitled),
        (10197, MarketDataNotEntitled),
        (200, ContractNotFound),
        (201, OrderRejected),
        (1100, BrokerUnavailable),
        (502, BrokerUnavailable),
    ],
)
def test_classify_ib_error_known_codes(code, expected):
    err = classify_ib_error(code, "msg")
    assert isinstance(err, expected)
    assert "msg" in str(err) or str(code) in str(err)


@pytest.mark.parametrize("code", [2104, 2106, 2158])
def test_classify_ib_error_benign_info_codes_return_none(code):
    assert classify_ib_error(code, "data farm OK") is None


def test_classify_ib_error_unknown_returns_none():
    assert classify_ib_error(99999, "mystery") is None
```

Run `.venv/bin/pytest tests/test_errors.py -v` → FAIL (module missing).

- [ ] **Step 2 — implement** `ibkr_mcp/core/errors.py`:

```python
"""Typed IBKR error domain + classifiers. Pure stdlib — no ib_async, no mcp.

The MCP tool layer lets these propagate; FastMCP serializes str(exc) to the
client, so each error must carry an actionable, human-readable message.
"""


class IBKRError(Exception):
    """Base for typed IBKR errors. `code` is a stable machine-readable tag."""

    code = "IBKR_ERROR"


class BrokerUnavailable(IBKRError):
    code = "BROKER_UNAVAILABLE"


class MarketDataNotEntitled(IBKRError):
    code = "MARKET_DATA_NOT_ENTITLED"


class OrderRejected(IBKRError):
    code = "ORDER_REJECTED"


class ContractNotFound(IBKRError):
    code = "CONTRACT_NOT_FOUND"


def broker_unavailable_from_connect(exc: Exception, host: str, port: int) -> BrokerUnavailable:
    """Map a connectAsync failure to a BrokerUnavailable with an actionable hint."""
    if isinstance(exc, ConnectionRefusedError):
        hint = "nothing is listening — is IB Gateway/TWS running and logged in?"
    elif isinstance(exc, TimeoutError):
        hint = (
            "the socket opened but the IBKR API handshake did not complete — check that "
            "the API is enabled and any 'accept incoming connection' dialog is approved."
        )
    else:
        hint = str(exc) or exc.__class__.__name__
    return BrokerUnavailable(f"IB Gateway not reachable on {host}:{port}: {hint}")


# IBKR error codes we classify. Benign info codes (data-farm OK, etc.) → None.
_MARKET_DATA_NOT_ENTITLED = {354, 10089, 10197}
_BROKER_UNAVAILABLE = {502, 504, 1100, 1300, 2110}
_BENIGN_INFO = {2104, 2106, 2107, 2108, 2158}


def classify_ib_error(code: int, message: str) -> IBKRError | None:
    """Map an IBKR errorEvent (code, message) to a typed error, or None if benign/unknown."""
    if code in _BENIGN_INFO:
        return None
    if code in _MARKET_DATA_NOT_ENTITLED:
        return MarketDataNotEntitled(f"Market data not subscribed (IBKR {code}): {message}")
    if code == 200:
        return ContractNotFound(f"No security definition found (IBKR 200): {message}")
    if code == 201:
        return OrderRejected(f"Order rejected (IBKR 201): {message}")
    if code in _BROKER_UNAVAILABLE:
        return BrokerUnavailable(f"Broker connectivity issue (IBKR {code}): {message}")
    return None
```

Run → PASS. Commit: `git add ibkr_mcp/core/errors.py tests/test_errors.py && git commit -m "feat(core): typed IBKR error domain + classifiers (M-errors §13)"`

---

### Task 2: wrap connect failures in `core/connection.py`

**Files:** Modify `ibkr_mcp/core/connection.py`; Test `tests/test_connection.py` (append).

- [ ] **Step 1 — append failing test** to `tests/test_connection.py`:

```python
import pytest

from ibkr_mcp.core.errors import BrokerUnavailable


class _RefusingIB:
    def isConnected(self):
        return False

    async def connectAsync(self, host, port, clientId, readonly=False, **kw):
        raise ConnectionRefusedError(61, "Connection refused")

    def disconnect(self):
        return None


async def test_ensure_connected_maps_refused_to_broker_unavailable():
    conn = IBKRConnection("127.0.0.1", 4001, 1, ib_factory=lambda: _RefusingIB())
    with pytest.raises(BrokerUnavailable) as e:
        await conn.ensure_connected()
    assert "127.0.0.1:4001" in str(e.value)
```

(Reuse the existing `_FakeIB` happy-path tests already in the file — they must keep passing.)

Run `.venv/bin/pytest tests/test_connection.py -v` → the new test FAILS (raw ConnectionRefusedError, not BrokerUnavailable).

- [ ] **Step 2 — modify** `ensure_connected` in `ibkr_mcp/core/connection.py`:

Add the import near the top (after the existing imports):
```python
from ibkr_mcp.core.errors import broker_unavailable_from_connect
```
Replace the body of `ensure_connected`:
```python
    async def ensure_connected(self) -> None:
        if self._ib.isConnected():
            return
        try:
            await self._ib.connectAsync(
                self.host, self.port, clientId=self.client_id, readonly=self.readonly
            )
        except (OSError, TimeoutError) as exc:
            # OSError covers ConnectionRefusedError; TimeoutError covers the apiStart
            # handshake stall (gateway up but API blocked / accept-dialog pending).
            raise broker_unavailable_from_connect(exc, self.host, self.port) from exc
```

Run → PASS (new + existing). Note: `core/connection.py` importing `core/errors` keeps the extractable-core invariant (both are `core/`, neither imports mcp).

Commit: `git add ibkr_mcp/core/connection.py tests/test_connection.py && git commit -m "feat(core): map connect failures to BrokerUnavailable (M-errors §13)"`

---

## After all tasks

- `.venv/bin/pytest -v` → expect 81 + ~9 (errors) + 1 (connection) = ~91 passed, 2 skipped (report actual).
- `.venv/bin/ruff check .` + `.venv/bin/ruff format --check .` clean.
- Both architecture guards still green (`errors.py` is pure stdlib; `connection.py` imports `core.errors`, not mcp/ib_async-for-errors).

## Self-review notes (author)
- Spec §13 coverage: connect-refused/timeout → BrokerUnavailable (Task 2); IBKR code map 354/10089/10197/200/201/502/504/1100 + benign 2104/2106 → classify_ib_error (Task 1). The classifier is wired into market_data + order placement in M3b/M4 respectively (not here).
- Out of scope: market_data entitlement degradation USING these types (M3b), order-rejection USING OrderRejected (M4). This milestone only defines the types + the connect-path wiring.
- Directly fixes the live-surfaced raw-errno UX: read tools against a down Gateway now raise a clean BrokerUnavailable with guidance.
