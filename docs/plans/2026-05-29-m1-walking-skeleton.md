# ibkr-mcp Milestone 1 — Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the FastMCP + ib_async marriage end-to-end — from an MCP client (Claude Desktop/Code), call a read tool that round-trips to a live IBKR **paper** Gateway and returns real account data.

**Architecture:** Thinnest vertical slice across the approved `core/` ↔ `mcp/` seam (see `docs/2026-05-29-ibkr-mcp-design.md` §7). `core/` owns the `ib_async.IB()` lifecycle and IBKR reads (imports `ib_async`, never `mcp`/FastMCP). `mcp/` is a thin FastMCP layer exposing two tools (`ibkr_health`, `get_account_summary`). Lazy-connect-at-tool-entry pattern (confirmed against the `Hellek1/ib-mcp` reference; **no `nest_asyncio`** — `ib_async` is asyncio-native and runs in FastMCP's loop via awaited `*Async` methods).

**Tech Stack:** Python 3.11/3.12 (pinned — `nest_asyncio` transitive dep breaks on 3.13/3.14), `ib_async>=2.0.1`, official MCP SDK `mcp>=1.2` (`from mcp.server.fastmcp import FastMCP`), `pytest` + `pytest-asyncio`, `ruff`.

---

## ⚠ Prerequisite for verification (Tasks 8)

M1 verification needs a **running IBKR paper Gateway**:
- An IBKR account with **paper trading** enabled.
- IB Gateway (or TWS) running, logged into the **paper** account, with API enabled, **socket port 4002** on `127.0.0.1`, "Read-Only API" can stay ON for M1 (we only read).
- If you don't have this yet, Tasks 1–7 + 9 (all pure-logic, no Gateway) still complete; Task 8 is gated behind the env var `IBKR_MCP_RUN_INTEGRATION=1` and is skipped otherwise.

## Milestone roadmap (this plan = M1 only)

- **M1 — Walking skeleton (this plan):** scaffolding + minimal `core` + 2 read tools + real paper round-trip. Retires the integration risk.
- M2 — `core/safety/` (guardrails, idempotency, kill-switch) — pure logic, strict TDD. The differentiator.
- M3 — full read tools + `core/contracts` + `core/market_data` (entitlement-aware).
- M4 — write tools + guardrail wiring + `preview_order`→`confirm_order` flow.
- M5 — packaging (`uvx`/`pip`), LICENSE (MIT), DISCLAIMER, public README (English).

Each milestone gets its own plan, written after the previous one is executed and verified.

> **Note on the `mcp/` subpackage name:** it intentionally shadows nothing — inside `ibkr_mcp/mcp/`, `from mcp.server.fastmcp import FastMCP` resolves to the top-level installed `mcp` package under Python 3 absolute-import semantics. Internal references use relative imports (`from ibkr_mcp.core...`). This matches the approved spec §7.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `README.md` (minimal run instructions; full public README is M5)
- Create: `ibkr_mcp/__init__.py`
- Create: `ibkr_mcp/core/__init__.py`
- Create: `ibkr_mcp/mcp/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "ibkr-mcp"
version = "0.0.1"
description = "Guarded Interactive Brokers MCP server — safe LLM trading access"
requires-python = ">=3.11,<3.13"
license = { text = "MIT" }
dependencies = [
    "ib_async>=2.0.1",
    "mcp>=1.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.6",
]

[project.scripts]
ibkr-mcp = "ibkr_mcp.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["ibkr_mcp"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "integration: requires a running IBKR paper Gateway (deselect with -m 'not integration')",
]

[tool.ruff]
target-version = "py311"
line-length = 100
```

- [ ] **Step 2: Create the package skeleton files**

`README.md`:
```markdown
# ibkr-mcp (working name)

Guarded Interactive Brokers MCP server. Paper-trading by default. **Not financial advice.**

## Run the M1 skeleton against a paper Gateway

1. Start IB Gateway / TWS logged into your **paper** account, API enabled, port 4002.
2. `pip install -e ".[dev]"`
3. `IBKR_PORT=4002 python -m ibkr_mcp` (or add to your MCP client config).

See `docs/` for the design and plans.
```

`ibkr_mcp/__init__.py`:
```python
"""ibkr-mcp — guarded Interactive Brokers MCP server."""

__version__ = "0.0.1"
```

`ibkr_mcp/core/__init__.py`, `ibkr_mcp/mcp/__init__.py`, `tests/__init__.py`: empty files.

- [ ] **Step 3: Install and verify the package imports**

Run: `pip install -e ".[dev]"`
Then: `python -c "import ibkr_mcp; print(ibkr_mcp.__version__)"`
Expected: prints `0.0.1`

Run: `ruff check .`
Expected: no errors (or "All checks passed!").

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml README.md ibkr_mcp tests
git commit -m "chore: scaffold ibkr-mcp package (M1)"
```

---

### Task 2: `core/models.py` — domain dataclasses

**Files:**
- Create: `ibkr_mcp/core/models.py`
- Test: `tests/test_models.py`

These copy the Aegis `BrokerAdapter` v2 shapes (design §7) so a future `ibkr-core` extraction backs an Aegis adapter without translation. Pure data — no `ib_async`, no `mcp`.

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
from datetime import datetime, timezone

from ibkr_mcp.core.models import AccountInfo, BrokerHealth


def test_broker_health_defaults():
    h = BrokerHealth(connected=False)
    assert h.connected is False
    assert h.last_heartbeat_at is None
    assert h.latency_ms is None


def test_broker_health_connected():
    ts = datetime.now(timezone.utc)
    h = BrokerHealth(connected=True, last_heartbeat_at=ts, latency_ms=1.5)
    assert h.connected is True
    assert h.last_heartbeat_at == ts
    assert h.latency_ms == 1.5


def test_account_info_fields():
    a = AccountInfo(
        total_value=100_000.0,
        cash=50_000.0,
        buying_power=200_000.0,
        positions_value=50_000.0,
        unrealized_pnl=1_234.5,
    )
    assert a.total_value == 100_000.0
    assert a.buying_power == 200_000.0
    assert a.unrealized_pnl == 1_234.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ibkr_mcp.core.models'`

- [ ] **Step 3: Write minimal implementation**

`ibkr_mcp/core/models.py`:
```python
"""Domain dataclasses — copies of the Aegis BrokerAdapter v2 shapes.

Kept aligned with Aegis backend/app/brokers/base.py so a future `ibkr-core`
package can back an IBKRBrokerAdapter without translation.
This module imports neither ib_async nor mcp (extractable-core invariant).
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class BrokerHealth:
    connected: bool
    last_heartbeat_at: datetime | None = None
    latency_ms: float | None = None


@dataclass
class AccountInfo:
    total_value: float
    cash: float
    buying_power: float
    positions_value: float
    unrealized_pnl: float
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ibkr_mcp/core/models.py tests/test_models.py
git commit -m "feat(core): add BrokerHealth and AccountInfo models (M1)"
```

---

### Task 3: `core/connection.py` — IBKRConnection lifecycle

**Files:**
- Create: `ibkr_mcp/core/connection.py`
- Test: `tests/test_connection.py`

The IB lifecycle. `ib_factory` is injectable so the pure parts (health mapping, paper detection, lazy-connect guard) are unit-tested with a fake IB — no Gateway needed. The real round-trip is Task 8.

- [ ] **Step 1: Write the failing test**

`tests/test_connection.py`:
```python
from ibkr_mcp.core.connection import IBKRConnection


class _FakeIB:
    def __init__(self):
        self._connected = False
        self.connect_calls = []

    def isConnected(self):
        return self._connected

    async def connectAsync(self, host, port, clientId, readonly=False, **kwargs):
        self.connect_calls.append((host, port, clientId, readonly))
        self._connected = True

    def disconnect(self):
        self._connected = False
        return None


def _make(port=4002, readonly=True):
    fake = _FakeIB()
    conn = IBKRConnection(
        "127.0.0.1", port, 1, readonly=readonly, ib_factory=lambda: fake
    )
    return conn, fake


def test_is_paper_for_paper_ports():
    conn, _ = _make(port=4002)
    assert conn.is_paper is True
    conn2, _ = _make(port=4001)
    assert conn2.is_paper is False


async def test_health_reflects_connection_state():
    conn, fake = _make()
    h = await conn.health()
    assert h.connected is False
    assert h.last_heartbeat_at is None

    fake._connected = True
    h2 = await conn.health()
    assert h2.connected is True
    assert h2.last_heartbeat_at is not None


async def test_ensure_connected_connects_once():
    conn, fake = _make(port=4002, readonly=True)
    await conn.ensure_connected()
    assert fake.connect_calls == [("127.0.0.1", 4002, 1, True)]

    # Already connected → no second connect.
    await conn.ensure_connected()
    assert len(fake.connect_calls) == 1


def test_disconnect_is_safe_when_not_connected():
    conn, fake = _make()
    conn.disconnect()  # must not raise
    assert fake.isConnected() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_connection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ibkr_mcp.core.connection'`

- [ ] **Step 3: Write minimal implementation**

`ibkr_mcp/core/connection.py`:
```python
"""IBKRConnection — owns the single ib_async.IB() instance and its lifecycle.

Imports ib_async; MUST NOT import mcp/FastMCP (extractable-core invariant).
Lazy-connect-at-tool-entry pattern: the server runs even if the Gateway is
down; health() reports the state and tools call ensure_connected() first.
"""

from collections.abc import Callable
from datetime import datetime, timezone

import ib_async

from ibkr_mcp.core.models import BrokerHealth

# IBKR socket convention: paper = 4002 (Gateway) / 7497 (TWS),
# live = 4001 (Gateway) / 7496 (TWS).
_PAPER_PORTS = frozenset({4002, 7497})


class IBKRConnection:
    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        *,
        readonly: bool = True,
        ib_factory: Callable[[], "ib_async.IB"] = ib_async.IB,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.readonly = readonly
        self._ib = ib_factory()

    @property
    def ib(self) -> "ib_async.IB":
        return self._ib

    @property
    def is_paper(self) -> bool:
        return self.port in _PAPER_PORTS

    async def ensure_connected(self) -> None:
        if self._ib.isConnected():
            return
        await self._ib.connectAsync(
            self.host, self.port, clientId=self.client_id, readonly=self.readonly
        )

    async def health(self) -> BrokerHealth:
        connected = self._ib.isConnected()
        return BrokerHealth(
            connected=connected,
            last_heartbeat_at=datetime.now(timezone.utc) if connected else None,
        )

    def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_connection.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add ibkr_mcp/core/connection.py tests/test_connection.py
git commit -m "feat(core): add IBKRConnection lifecycle (lazy-connect, health) (M1)"
```

---

### Task 4: `core/account.py` — account summary read

**Files:**
- Create: `ibkr_mcp/core/account.py`
- Test: `tests/test_account.py`

Maps `ib.accountSummaryAsync()` rows (`AccountValue` objects with `.tag`/`.value`) to `AccountInfo`. Tested with a fake IB.

- [ ] **Step 1: Write the failing test**

`tests/test_account.py`:
```python
import pytest

from ibkr_mcp.core.account import get_account_summary


class _Row:
    def __init__(self, tag, value):
        self.tag = tag
        self.value = value


class _FakeIB:
    def __init__(self, rows):
        self._rows = rows

    async def accountSummaryAsync(self, account=""):
        return self._rows


@pytest.fixture
def rows():
    return [
        _Row("NetLiquidation", "100000"),
        _Row("TotalCashValue", "50000"),
        _Row("BuyingPower", "200000"),
        _Row("GrossPositionValue", "50000"),
        _Row("UnrealizedPnL", "1234.5"),
        _Row("SomethingElse", "ignored"),
    ]


async def test_maps_known_tags(rows):
    acct = await get_account_summary(_FakeIB(rows))
    assert acct.total_value == 100000.0
    assert acct.cash == 50000.0
    assert acct.buying_power == 200000.0
    assert acct.positions_value == 50000.0
    assert acct.unrealized_pnl == 1234.5


async def test_missing_tag_defaults_to_zero():
    acct = await get_account_summary(_FakeIB([_Row("NetLiquidation", "10")]))
    assert acct.total_value == 10.0
    assert acct.cash == 0.0
    assert acct.buying_power == 0.0


async def test_non_numeric_value_defaults_to_zero():
    acct = await get_account_summary(_FakeIB([_Row("NetLiquidation", "N/A")]))
    assert acct.total_value == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_account.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ibkr_mcp.core.account'`

- [ ] **Step 3: Write minimal implementation**

`ibkr_mcp/core/account.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_account.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ibkr_mcp/core/account.py tests/test_account.py
git commit -m "feat(core): add get_account_summary read (M1)"
```

---

### Task 5: `mcp/config.py` — environment config

**Files:**
- Create: `ibkr_mcp/mcp/config.py`
- Test: `tests/test_config.py`

Pure parsing of env vars to a `Config`. Defaults to **paper** port 4002.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from ibkr_mcp.mcp.config import Config


def test_defaults_when_env_empty():
    cfg = Config.from_env({})
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 4002  # paper by default
    assert cfg.client_id == 1
    assert cfg.read_only is True


def test_reads_env():
    cfg = Config.from_env(
        {
            "IBKR_HOST": "192.168.1.10",
            "IBKR_PORT": "4001",
            "IBKR_CLIENT_ID": "7",
            "IBKR_READ_ONLY": "false",
        }
    )
    assert cfg.host == "192.168.1.10"
    assert cfg.port == 4001
    assert cfg.client_id == 7
    assert cfg.read_only is False


def test_read_only_truthiness():
    assert Config.from_env({"IBKR_READ_ONLY": "0"}).read_only is False
    assert Config.from_env({"IBKR_READ_ONLY": "true"}).read_only is True
    assert Config.from_env({"IBKR_READ_ONLY": "1"}).read_only is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ibkr_mcp.mcp.config'`

- [ ] **Step 3: Write minimal implementation**

`ibkr_mcp/mcp/config.py`:
```python
"""MCP-layer configuration. No ib_async import here."""

import os
from dataclasses import dataclass
from collections.abc import Mapping

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 4002  # paper Gateway by default
    client_id: int = 1
    read_only: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        return cls(
            host=env.get("IBKR_HOST", "127.0.0.1"),
            port=int(env.get("IBKR_PORT", "4002")),
            client_id=int(env.get("IBKR_CLIENT_ID", "1")),
            read_only=env.get("IBKR_READ_ONLY", "true").strip().lower() in _TRUTHY,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ibkr_mcp/mcp/config.py tests/test_config.py
git commit -m "feat(mcp): add env Config (paper default) (M1)"
```

---

### Task 6: `mcp/tools_read.py` — tool logic (testable, FastMCP-free)

**Files:**
- Create: `ibkr_mcp/mcp/tools_read.py`
- Test: `tests/test_tools_read.py`

Tool *logic* lives in plain async functions taking an `IBKRConnection`-like object, returning LLM-friendly dicts. This keeps the logic unit-testable without FastMCP internals; the FastMCP decorators (Task 7) are thin wrappers.

- [ ] **Step 1: Write the failing test**

`tests/test_tools_read.py`:
```python
from datetime import datetime, timezone

from ibkr_mcp.core.models import AccountInfo, BrokerHealth
from ibkr_mcp.mcp import tools_read


class _FakeAcctIB:
    async def accountSummaryAsync(self, account=""):
        class _R:
            def __init__(self, tag, value):
                self.tag, self.value = tag, value

        return [_R("NetLiquidation", "100000"), _R("TotalCashValue", "40000")]


class _FakeConn:
    def __init__(self, connected):
        self._connected = connected
        self.ensured = False
        self.ib = _FakeAcctIB()

    @property
    def is_paper(self):
        return True

    async def ensure_connected(self):
        self.ensured = True

    async def health(self):
        ts = datetime.now(timezone.utc) if self._connected else None
        return BrokerHealth(connected=self._connected, last_heartbeat_at=ts)


async def test_health_tool_shape():
    out = await tools_read.health(_FakeConn(connected=True))
    assert out["connected"] is True
    assert out["is_paper"] is True
    assert out["last_heartbeat_at"] is not None


async def test_health_tool_disconnected():
    out = await tools_read.health(_FakeConn(connected=False))
    assert out["connected"] is False
    assert out["last_heartbeat_at"] is None


async def test_account_summary_tool_ensures_connection_and_maps():
    conn = _FakeConn(connected=True)
    out = await tools_read.account_summary(conn)
    assert conn.ensured is True
    assert out["total_value"] == 100000.0
    assert out["cash"] == 40000.0
    assert out["buying_power"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tools_read.py -v`
Expected: FAIL — `ImportError: cannot import name 'tools_read'` (module missing)

- [ ] **Step 3: Write minimal implementation**

`ibkr_mcp/mcp/tools_read.py`:
```python
"""Read-tool logic — plain async functions, FastMCP-free for testability.

Takes an IBKRConnection. server.py wraps these in @app.tool() decorators.
"""

from ibkr_mcp.core.account import get_account_summary
from ibkr_mcp.core.connection import IBKRConnection


async def health(conn: IBKRConnection) -> dict:
    h = await conn.health()
    return {
        "connected": h.connected,
        "is_paper": conn.is_paper,
        "last_heartbeat_at": (
            h.last_heartbeat_at.isoformat() if h.last_heartbeat_at else None
        ),
    }


async def account_summary(conn: IBKRConnection) -> dict:
    await conn.ensure_connected()
    acct = await get_account_summary(conn.ib)
    return {
        "total_value": acct.total_value,
        "cash": acct.cash,
        "buying_power": acct.buying_power,
        "positions_value": acct.positions_value,
        "unrealized_pnl": acct.unrealized_pnl,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tools_read.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ibkr_mcp/mcp/tools_read.py tests/test_tools_read.py
git commit -m "feat(mcp): add read-tool logic (health, account_summary) (M1)"
```

---

### Task 7: `mcp/server.py` + `__main__.py` — FastMCP wiring

**Files:**
- Create: `ibkr_mcp/mcp/server.py`
- Create: `ibkr_mcp/__main__.py`
- Test: `tests/test_server.py`

Wires the two tools into a FastMCP app. `build_server(conn)` takes a connection (so tests can pass a fake). `__main__.main()` loads config, builds, runs, and disconnects on exit.

- [ ] **Step 1: Write the failing test**

`tests/test_server.py`:
```python
from mcp.server.fastmcp import FastMCP

from ibkr_mcp.mcp.server import build_server


class _FakeConn:
    is_paper = True

    async def ensure_connected(self):
        pass

    async def health(self):
        from ibkr_mcp.core.models import BrokerHealth

        return BrokerHealth(connected=False)


def test_build_server_returns_fastmcp_without_connecting():
    app = build_server(_FakeConn())
    assert isinstance(app, FastMCP)


async def test_registered_tool_names():
    app = build_server(_FakeConn())
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert {"ibkr_health", "get_account_summary"} <= names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ibkr_mcp.mcp.server'`

- [ ] **Step 3: Write minimal implementation**

`ibkr_mcp/mcp/server.py`:
```python
"""FastMCP server wiring — thin layer over core/ + tools_read.

Imports the installed `mcp` SDK (top-level, not this subpackage) and core/.
Never imports ib_async directly.
"""

from mcp.server.fastmcp import FastMCP

from ibkr_mcp.core.connection import IBKRConnection
from ibkr_mcp.mcp import tools_read


def build_server(conn: IBKRConnection) -> FastMCP:
    app = FastMCP(
        "ibkr-mcp",
        instructions=(
            "Guarded Interactive Brokers access. Paper-trading by default. "
            "Read-only tools only in this build."
        ),
    )

    @app.tool()
    async def ibkr_health() -> dict:
        """Connection state to IB Gateway: connected, paper vs live, last heartbeat."""
        return await tools_read.health(conn)

    @app.tool()
    async def get_account_summary() -> dict:
        """Account summary: net liquidation, cash, buying power, positions value, unrealized P&L."""
        return await tools_read.account_summary(conn)

    return app
```

`ibkr_mcp/__main__.py`:
```python
"""Console entrypoint: `ibkr-mcp` / `python -m ibkr_mcp`."""

from ibkr_mcp.core.connection import IBKRConnection
from ibkr_mcp.mcp.config import Config
from ibkr_mcp.mcp.server import build_server


def main() -> None:
    config = Config.from_env()
    conn = IBKRConnection(
        config.host, config.port, config.client_id, readonly=config.read_only
    )
    app = build_server(conn)
    try:
        app.run()  # stdio transport by default
    finally:
        conn.disconnect()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_server.py -v`
Expected: PASS (2 passed)

(If `app.list_tools()` signature differs in your installed `mcp` version and the second test errors on the call itself, keep the first test, and verify tool registration via the Task 8 integration run instead. Do not delete the assertion — adapt the accessor.)

- [ ] **Step 5: Commit**

```bash
git add ibkr_mcp/mcp/server.py ibkr_mcp/__main__.py tests/test_server.py
git commit -m "feat(mcp): wire FastMCP server with two read tools + entrypoint (M1)"
```

---

### Task 8: Integration verification — real paper round-trip

**Files:**
- Create: `tests/test_integration_paper.py`

This is the milestone's reason to exist: prove the FastMCP + ib_async stack round-trips to a **real** paper Gateway. Gated behind `IBKR_MCP_RUN_INTEGRATION=1` (skipped in normal/CI runs).

- [ ] **Step 1: Write the integration test**

`tests/test_integration_paper.py`:
```python
"""Real paper-Gateway round-trip. Requires a logged-in IB paper Gateway on port 4002.

Run explicitly:  IBKR_MCP_RUN_INTEGRATION=1 pytest -m integration -v
"""

import os

import pytest

from ibkr_mcp.core.connection import IBKRConnection
from ibkr_mcp.mcp import tools_read

pytestmark = pytest.mark.integration

_RUN = os.environ.get("IBKR_MCP_RUN_INTEGRATION") == "1"


@pytest.mark.skipif(not _RUN, reason="set IBKR_MCP_RUN_INTEGRATION=1 with a paper Gateway running")
async def test_health_and_account_against_paper():
    conn = IBKRConnection("127.0.0.1", 4002, 99, readonly=True)
    try:
        await conn.ensure_connected()
        health = await tools_read.health(conn)
        assert health["connected"] is True
        assert health["is_paper"] is True

        acct = await tools_read.account_summary(conn)
        # A funded paper account reports a positive net liquidation value.
        assert acct["total_value"] > 0
        print("PAPER ACCOUNT SUMMARY:", acct)
    finally:
        conn.disconnect()
```

- [ ] **Step 2: Run the full suite WITHOUT the Gateway (integration skipped)**

Run: `pytest -v`
Expected: all unit tests PASS; `test_health_and_account_against_paper` shows SKIPPED.

- [ ] **Step 3: Run the integration test WITH a paper Gateway**

Prerequisite: IB Gateway logged into the paper account, API on, port 4002.
Run: `IBKR_MCP_RUN_INTEGRATION=1 pytest -m integration -v -s`
Expected: PASS, and the printed `PAPER ACCOUNT SUMMARY: {...}` shows real numbers.

- [ ] **Step 4: Manual end-to-end via an MCP client (the real proof)**

Add to your MCP client config (e.g. `claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "ibkr-mcp": {
      "command": "python",
      "args": ["-m", "ibkr_mcp"],
      "env": { "IBKR_PORT": "4002", "IBKR_CLIENT_ID": "99" }
    }
  }
}
```
Restart the client, then ask it to call `ibkr_health` and `get_account_summary`.
Expected: the assistant returns your live paper connection state and account numbers.

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration_paper.py
git commit -m "test: add gated paper-Gateway integration round-trip (M1)"
```

---

### Task 9: Architecture invariant test — protect the `core/` seam

**Files:**
- Create: `tests/test_architecture.py`

Locks the load-bearing decision from day one: `core/` must never import `mcp`/FastMCP (so it stays extractable into `ibkr-core`).

- [ ] **Step 1: Write the failing test**

`tests/test_architecture.py`:
```python
"""Guard the extractable-core invariant: ibkr_mcp/core/ never imports mcp or fastmcp."""

import pathlib

CORE_DIR = pathlib.Path(__file__).resolve().parent.parent / "ibkr_mcp" / "core"


def test_core_never_imports_mcp_or_fastmcp():
    offenders = []
    for py in CORE_DIR.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            # Allow our own package; forbid the MCP SDK / FastMCP.
            if (
                "fastmcp" in stripped
                or stripped.startswith("import mcp")
                or stripped.startswith("from mcp")
            ):
                offenders.append(f"{py.name}:{lineno}: {stripped}")
    assert not offenders, "core/ must not depend on MCP layer:\n" + "\n".join(offenders)
```

- [ ] **Step 2: Run test to verify it passes immediately**

Run: `pytest tests/test_architecture.py -v`
Expected: PASS (the current `core/` only imports `ib_async` and `ibkr_mcp.core.*`).

(This test passes on first write because the invariant already holds — it is a *regression guard* for future milestones, not red-green. To convince yourself it actually catches violations, temporarily add `from mcp.server.fastmcp import FastMCP` to `ibkr_mcp/core/models.py`, run the test, confirm it FAILS, then remove the line.)

- [ ] **Step 3: Run the whole suite + lint**

Run: `pytest -v` then `ruff check .`
Expected: all unit tests PASS, integration SKIPPED, ruff clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_architecture.py
git commit -m "test: guard core/ vs mcp import seam (M1)"
```

---

## Self-review notes (author)

- **Spec coverage (M1 slice):** topology §6 → Task 7; `core/`↔`mcp/` seam §7 → Tasks 2–7 + invariant Task 9; lazy-connect lifecycle §8 → Task 3; `ibkr_health` + `get_account_summary` from the §9 tool table → Tasks 6–7; paper-by-default §10.1/§12 → Config default port 4002 (Task 5) + `is_paper` (Task 3). Guardrails (§10), contracts/market-data (§11), write tools (§9/§10) are **deliberately out of M1** → M2–M4.
- **No placeholders:** every code/test/command step is concrete and runnable.
- **Type consistency:** `IBKRConnection(host, port, client_id, *, readonly, ib_factory)`, `.is_paper`, `.ib`, `ensure_connected()`, `health()`, `disconnect()`; `get_account_summary(ib)`; `tools_read.health(conn)` / `tools_read.account_summary(conn)`; `Config.from_env(env)` — names match across Tasks 3/4/6/7/8.
- **ib_async API verified** (context7, official docs): `connectAsync(host, port, clientId, readonly=...)`, `isConnected()`, `disconnect()`, `accountSummaryAsync(account='')` returning rows with `.tag`/`.value`.
