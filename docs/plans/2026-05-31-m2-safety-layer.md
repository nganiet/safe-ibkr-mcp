# ibkr-mcp Milestone 2 — Safety Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans. TDD is mandatory for this milestone — every behavior gets a failing test first.

**Goal:** Build the server-enforced safety primitives in `ibkr_mcp/core/safety/` — the project's headline differentiator. Pure logic, strict TDD, no IBKR/MCP dependency.

**Architecture:** Three modules under `ibkr_mcp/core/safety/`, all transport-agnostic and `ib_async`-free / `mcp`-free (extractable-core invariant). They are *primitives* — the actual `preview_order`→`confirm_order` tool wiring that consumes them is M4. M2 proves each primitive in isolation.

**Tech Stack:** Python 3.11/3.12, stdlib only (`sqlite3`, `secrets`, `pathlib`, `datetime`, `decimal`, `dataclasses`). Tests via `.venv/bin/pytest -v`. Reference: design spec `docs/2026-05-29-ibkr-mcp-design.md` §10 (safety model) + §14 (mandatory test cases) + §17 (token = opaque random + SQLite + params hash + TTL).

---

## Design decisions resolved (read before implementing)

1. **File scope (3 files, per PO):** `killswitch.py`, `guardrails.py`, `idempotency.py`, plus `__init__.py`. Each module defines its OWN exception type (no shared errors module in M2) to keep the 3-file scope.
2. **Where the preview token lives:** in `idempotency.py` as a second class `PreviewTokenStore`, alongside `IdempotencyStore` — both back onto the same SQLite `state.db` (spec §17: opaque random + SQLite + params hash + TTL). The module owns `state.db`. (Future SRP split into `previews.py` is acceptable; deferred.)
3. **Testability of time:** anything with a TTL takes an injectable `now` callable (`Callable[[], datetime]`, default `lambda: datetime.now(timezone.utc)`). This is how the "expired token" case is tested deterministically — NO `sleep`.
4. **Testability of state path:** `IdempotencyStore` / `PreviewTokenStore` take an injectable `db_path` (tests pass a `tmp_path` file); default `~/.ibkr-mcp/state.db`. `KillSwitch` takes an injectable `path`; default `~/.ibkr-mcp/KILL`. Tests NEVER touch the real `~/.ibkr-mcp/`.
5. **Guardrail re-check semantics:** `GuardrailPolicy.check_order(...)` is a pure, repeatable check raising on violation. "Checked at preview AND re-checked at confirm" (spec §10.4) is satisfied because the same call is safe to invoke twice with identical results — M2 tests assert repeatability; the actual two-call wiring is M4.
6. **Architecture invariant:** the existing `tests/test_architecture.py::test_core_never_imports_mcp_or_fastmcp` already scans `ibkr_mcp/core` via `rglob("*.py")`, so `core/safety/*.py` is covered automatically. We add one explicit assertion that the safety modules exist and are non-empty (so the coverage is intentional, not incidental).
7. **Decimal for quantities** (matches the Aegis `OrderRequest.quantity: Decimal`); notional uses `float` USD (matches `max_order_notional_usd: float`).

---

### Task 1: `ibkr_mcp/core/safety/__init__.py` + `killswitch.py`

**Files:**
- Create: `ibkr_mcp/core/safety/__init__.py` (empty)
- Create: `ibkr_mcp/core/safety/killswitch.py`
- Test: `tests/test_killswitch.py`

**Behavior:** `KillSwitch` is engaged if EITHER a runtime flag is set OR a sentinel file exists (default `~/.ibkr-mcp/KILL`). `touch ~/.ibkr-mcp/KILL` must freeze trading instantly. `check()` raises `KillSwitchEngaged` when engaged.

- [ ] **Step 1 — failing test** `tests/test_killswitch.py`:

```python
import pytest

from ibkr_mcp.core.safety.killswitch import KillSwitch, KillSwitchEngaged


def test_not_engaged_by_default(tmp_path):
    ks = KillSwitch(path=tmp_path / "KILL")
    assert ks.is_engaged() is False
    ks.check()  # must not raise


def test_engaged_when_file_present(tmp_path):
    p = tmp_path / "KILL"
    ks = KillSwitch(path=p)
    p.write_text("frozen")  # simulates `touch ~/.ibkr-mcp/KILL`
    assert ks.is_engaged() is True
    with pytest.raises(KillSwitchEngaged):
        ks.check()


def test_engaged_when_runtime_armed(tmp_path):
    ks = KillSwitch(path=tmp_path / "KILL")
    ks.arm("manual stop")
    assert ks.is_engaged() is True
    with pytest.raises(KillSwitchEngaged):
        ks.check()
    ks.disarm()
    assert ks.is_engaged() is False


def test_check_message_includes_reason(tmp_path):
    ks = KillSwitch(path=tmp_path / "KILL")
    ks.arm("circuit breaker")
    with pytest.raises(KillSwitchEngaged, match="circuit breaker"):
        ks.check()
```

Run `.venv/bin/pytest tests/test_killswitch.py -v` → FAIL (module missing).

- [ ] **Step 2 — implement** `ibkr_mcp/core/safety/killswitch.py`:

```python
"""Kill switch — instant freeze of all write operations.

Engaged if a runtime flag is set OR a sentinel file exists (default
~/.ibkr-mcp/KILL), so `touch ~/.ibkr-mcp/KILL` freezes trading without
touching the running process. Pure logic — no ib_async, no mcp.
"""

from pathlib import Path


class KillSwitchEngaged(Exception):
    """Raised when a write is attempted while the kill switch is engaged."""


_DEFAULT_PATH = Path.home() / ".ibkr-mcp" / "KILL"


class KillSwitch:
    def __init__(self, path: Path | None = None, *, armed: bool = False) -> None:
        self._path = path if path is not None else _DEFAULT_PATH
        self._runtime_armed = armed
        self._reason: str | None = "armed at startup" if armed else None

    def arm(self, reason: str) -> None:
        self._runtime_armed = True
        self._reason = reason

    def disarm(self) -> None:
        self._runtime_armed = False
        self._reason = None

    def is_engaged(self) -> bool:
        return self._runtime_armed or self._path.exists()

    def check(self) -> None:
        if not self.is_engaged():
            return
        reason = self._reason if self._runtime_armed else f"sentinel file {self._path}"
        raise KillSwitchEngaged(f"Kill switch engaged ({reason}) — writes blocked.")
```

Run → PASS (4). Commit: `git add ibkr_mcp/core/safety/__init__.py ibkr_mcp/core/safety/killswitch.py tests/test_killswitch.py && git commit -m "feat(safety): add KillSwitch (file or runtime, blocks writes) (M2)"`

---

### Task 2: `ibkr_mcp/core/safety/guardrails.py`

**Files:**
- Create: `ibkr_mcp/core/safety/guardrails.py`
- Test: `tests/test_guardrails.py`

**Behavior:** `GuardrailPolicy` (frozen dataclass) holds the server-enforced limits. `check_order(...)` raises `GuardrailViolation(code, message)` on the first violation, in this order: paper/live gate → ticker allowlist → max qty → max notional. Repeatable (same inputs → same verdict).

- [ ] **Step 1 — failing test** `tests/test_guardrails.py`:

```python
from decimal import Decimal

import pytest

from ibkr_mcp.core.safety.guardrails import GuardrailPolicy, GuardrailViolation


def _policy(**kw):
    return GuardrailPolicy(**kw)


def test_passes_within_limits():
    p = _policy(max_order_qty=Decimal(100), max_order_notional_usd=50_000.0)
    p.check_order(ticker="AAPL", qty=Decimal(10), est_price=200.0, is_paper=True)  # no raise


def test_live_blocked_unless_allowed():
    p = _policy(allow_live=False)
    with pytest.raises(GuardrailViolation) as e:
        p.check_order(ticker="AAPL", qty=Decimal(1), est_price=10.0, is_paper=False)
    assert e.value.code == "LIVE_NOT_ALLOWED"


def test_live_allowed_when_opted_in():
    p = _policy(allow_live=True)
    p.check_order(ticker="AAPL", qty=Decimal(1), est_price=10.0, is_paper=False)  # no raise


def test_ticker_allowlist_blocks_off_list():
    p = _policy(ticker_allowlist=frozenset({"AAPL", "MSFT"}))
    with pytest.raises(GuardrailViolation) as e:
        p.check_order(ticker="TSLA", qty=Decimal(1), est_price=10.0, is_paper=True)
    assert e.value.code == "TICKER_NOT_ALLOWED"
    # on-list passes
    p.check_order(ticker="AAPL", qty=Decimal(1), est_price=10.0, is_paper=True)


def test_allowlist_none_means_unrestricted():
    p = _policy(ticker_allowlist=None)
    p.check_order(ticker="ANYTHING", qty=Decimal(1), est_price=10.0, is_paper=True)  # no raise


def test_max_qty_enforced():
    p = _policy(max_order_qty=Decimal(100))
    with pytest.raises(GuardrailViolation) as e:
        p.check_order(ticker="AAPL", qty=Decimal(101), est_price=10.0, is_paper=True)
    assert e.value.code == "MAX_QTY_EXCEEDED"


def test_max_notional_enforced():
    p = _policy(max_order_notional_usd=1_000.0)
    with pytest.raises(GuardrailViolation) as e:
        # 10 * 150 = 1500 > 1000
        p.check_order(ticker="AAPL", qty=Decimal(10), est_price=150.0, is_paper=True)
    assert e.value.code == "MAX_NOTIONAL_EXCEEDED"


def test_notional_skipped_when_price_unknown():
    # est_price=None (no market-data entitlement) → notional cap cannot apply, qty cap still does
    p = _policy(max_order_notional_usd=1.0)
    p.check_order(ticker="AAPL", qty=Decimal(1), est_price=None, is_paper=True)  # no raise


def test_check_is_repeatable():
    p = _policy(max_order_qty=Decimal(5))
    for _ in range(3):
        with pytest.raises(GuardrailViolation):
            p.check_order(ticker="AAPL", qty=Decimal(6), est_price=1.0, is_paper=True)
```

Run → FAIL (module missing).

- [ ] **Step 2 — implement** `ibkr_mcp/core/safety/guardrails.py`:

```python
"""Server-enforced order guardrails — paper/live gate, allowlist, size & notional caps.

Pure policy: no ib_async, no mcp. check_order() raises on the first violation and is
safe to call repeatedly (preview AND confirm) with identical results.
"""

from dataclasses import dataclass
from decimal import Decimal


class GuardrailViolation(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GuardrailPolicy:
    max_order_qty: Decimal | None = None
    max_order_notional_usd: float | None = None
    ticker_allowlist: frozenset[str] | None = None  # None = unrestricted
    allow_live: bool = False

    def check_order(
        self,
        *,
        ticker: str,
        qty: Decimal,
        est_price: float | None,
        is_paper: bool,
    ) -> None:
        if not is_paper and not self.allow_live:
            raise GuardrailViolation(
                "LIVE_NOT_ALLOWED",
                "Live trading is disabled (set allow_live + connect to a live port).",
            )
        if self.ticker_allowlist is not None and ticker not in self.ticker_allowlist:
            raise GuardrailViolation(
                "TICKER_NOT_ALLOWED", f"{ticker} is not in the configured allowlist."
            )
        if self.max_order_qty is not None and qty > self.max_order_qty:
            raise GuardrailViolation(
                "MAX_QTY_EXCEEDED",
                f"Order qty {qty} exceeds cap {self.max_order_qty}.",
            )
        if (
            self.max_order_notional_usd is not None
            and est_price is not None
            and float(qty) * est_price > self.max_order_notional_usd
        ):
            raise GuardrailViolation(
                "MAX_NOTIONAL_EXCEEDED",
                f"Order notional {float(qty) * est_price:.2f} USD exceeds cap "
                f"{self.max_order_notional_usd:.2f}.",
            )
```

Run → PASS (9). Commit: `git add ibkr_mcp/core/safety/guardrails.py tests/test_guardrails.py && git commit -m "feat(safety): add GuardrailPolicy (live gate, allowlist, qty/notional caps) (M2)"`

---

### Task 3: `ibkr_mcp/core/safety/idempotency.py` — IdempotencyStore + PreviewTokenStore

**Files:**
- Create: `ibkr_mcp/core/safety/idempotency.py`
- Test: `tests/test_idempotency.py`

**Behavior:**
- `IdempotencyStore` (SQLite): `remember(client_order_id, result: dict)` persists a result; `get(client_order_id) -> dict | None`. The confirm flow uses `get` first — if present, returns the stored result instead of re-placing → **never a double fill**. `remember` for an already-seen id is idempotent (keeps the first result).
- `PreviewTokenStore` (SQLite, injectable `now`): `issue(params_hash) -> token` (opaque, `secrets.token_urlsafe`); `consume(token, params_hash, ttl_seconds=60)` validates and single-uses the token, raising `UnknownToken` (not found / already consumed), `ExpiredToken` (older than ttl), or `ParamsMismatch` (params hash differs). On success it deletes the token (single-use) and returns None.

- [ ] **Step 1 — failing test** `tests/test_idempotency.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from ibkr_mcp.core.safety.idempotency import (
    ExpiredToken,
    IdempotencyStore,
    ParamsMismatch,
    PreviewTokenStore,
    UnknownToken,
)


# ---- IdempotencyStore ----

def test_get_returns_none_when_unseen(tmp_path):
    s = IdempotencyStore(db_path=tmp_path / "state.db")
    assert s.get("cli-1") is None


def test_remember_then_get_roundtrips(tmp_path):
    s = IdempotencyStore(db_path=tmp_path / "state.db")
    s.remember("cli-1", {"order_id": "X", "status": "FILLED"})
    assert s.get("cli-1") == {"order_id": "X", "status": "FILLED"}


def test_double_confirm_same_id_never_double_fills(tmp_path):
    s = IdempotencyStore(db_path=tmp_path / "state.db")
    placements = []

    def confirm(coid, result):
        seen = s.get(coid)
        if seen is not None:
            return seen  # idempotent replay — do NOT place again
        placements.append(coid)  # the (simulated) real order placement
        s.remember(coid, result)
        return result

    r1 = confirm("cli-42", {"order_id": "A", "status": "FILLED"})
    r2 = confirm("cli-42", {"order_id": "A", "status": "FILLED"})
    assert r1 == r2
    assert placements == ["cli-42"]  # placed exactly once


def test_remember_keeps_first_result(tmp_path):
    s = IdempotencyStore(db_path=tmp_path / "state.db")
    s.remember("cli-1", {"v": 1})
    s.remember("cli-1", {"v": 2})  # second remember must not overwrite
    assert s.get("cli-1") == {"v": 1}


def test_idempotency_persists_across_instances(tmp_path):
    db = tmp_path / "state.db"
    IdempotencyStore(db_path=db).remember("cli-1", {"ok": True})
    assert IdempotencyStore(db_path=db).get("cli-1") == {"ok": True}  # survives restart


# ---- PreviewTokenStore ----

class _Clock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t = self.t + timedelta(seconds=seconds)


def test_issue_then_consume_ok(tmp_path):
    clock = _Clock(datetime(2026, 5, 31, tzinfo=timezone.utc))
    s = PreviewTokenStore(db_path=tmp_path / "state.db", now=clock)
    tok = s.issue("hash-abc")
    assert isinstance(tok, str) and len(tok) >= 16
    s.consume(tok, "hash-abc")  # no raise


def test_consume_is_single_use(tmp_path):
    clock = _Clock(datetime(2026, 5, 31, tzinfo=timezone.utc))
    s = PreviewTokenStore(db_path=tmp_path / "state.db", now=clock)
    tok = s.issue("hash-abc")
    s.consume(tok, "hash-abc")
    with pytest.raises(UnknownToken):
        s.consume(tok, "hash-abc")  # already consumed


def test_expired_token_rejected(tmp_path):
    clock = _Clock(datetime(2026, 5, 31, tzinfo=timezone.utc))
    s = PreviewTokenStore(db_path=tmp_path / "state.db", now=clock)
    tok = s.issue("hash-abc")
    clock.advance(61)  # default ttl 60s
    with pytest.raises(ExpiredToken):
        s.consume(tok, "hash-abc", ttl_seconds=60)


def test_params_mismatch_rejected(tmp_path):
    clock = _Clock(datetime(2026, 5, 31, tzinfo=timezone.utc))
    s = PreviewTokenStore(db_path=tmp_path / "state.db", now=clock)
    tok = s.issue("hash-abc")
    with pytest.raises(ParamsMismatch):
        s.consume(tok, "hash-DIFFERENT")


def test_unknown_token_rejected(tmp_path):
    s = PreviewTokenStore(db_path=tmp_path / "state.db")
    with pytest.raises(UnknownToken):
        s.consume("never-issued", "hash-abc")
```

Run → FAIL (module missing).

- [ ] **Step 2 — implement** `ibkr_mcp/core/safety/idempotency.py`:

```python
"""SQLite-backed write-time safety state (~/.ibkr-mcp/state.db).

Two cohesive concerns over one state file:
- IdempotencyStore: client_order_id -> result, so a retried confirm never double-fills.
- PreviewTokenStore: opaque single-use preview tokens bound to a params hash, with TTL.
Pure logic — no ib_async, no mcp.
"""

import json
import secrets
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_DB = Path.home() / ".ibkr-mcp" / "state.db"


class UnknownToken(Exception):
    """Token not found (never issued or already consumed)."""


class ExpiredToken(Exception):
    """Token older than its TTL."""


class ParamsMismatch(Exception):
    """Token presented with a params hash different from issuance."""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    return conn


class IdempotencyStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path if db_path is not None else _DEFAULT_DB
        with _connect(self._db) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS idempotency "
                "(client_order_id TEXT PRIMARY KEY, result TEXT NOT NULL)"
            )

    def get(self, client_order_id: str) -> dict | None:
        with _connect(self._db) as c:
            row = c.execute(
                "SELECT result FROM idempotency WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        return json.loads(row[0]) if row is not None else None

    def remember(self, client_order_id: str, result: dict) -> None:
        # INSERT OR IGNORE keeps the FIRST result (idempotent).
        with _connect(self._db) as c:
            c.execute(
                "INSERT OR IGNORE INTO idempotency (client_order_id, result) VALUES (?, ?)",
                (client_order_id, json.dumps(result)),
            )


class PreviewTokenStore:
    def __init__(
        self,
        db_path: Path | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db_path if db_path is not None else _DEFAULT_DB
        self._now = now if now is not None else (lambda: datetime.now(timezone.utc))
        with _connect(self._db) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS preview_tokens "
                "(token TEXT PRIMARY KEY, params_hash TEXT NOT NULL, created_at TEXT NOT NULL)"
            )

    def issue(self, params_hash: str) -> str:
        token = secrets.token_urlsafe(24)
        with _connect(self._db) as c:
            c.execute(
                "INSERT INTO preview_tokens (token, params_hash, created_at) VALUES (?, ?, ?)",
                (token, params_hash, self._now().isoformat()),
            )
        return token

    def consume(self, token: str, params_hash: str, *, ttl_seconds: int = 60) -> None:
        with _connect(self._db) as c:
            row = c.execute(
                "SELECT params_hash, created_at FROM preview_tokens WHERE token = ?",
                (token,),
            ).fetchone()
            if row is None:
                raise UnknownToken("Preview token not found or already consumed.")
            stored_hash, created_at = row[0], datetime.fromisoformat(row[1])
            # Single-use: remove first so it cannot be replayed even if a check below fails.
            c.execute("DELETE FROM preview_tokens WHERE token = ?", (token,))
        if (self._now() - created_at).total_seconds() > ttl_seconds:
            raise ExpiredToken("Preview token has expired — re-run preview_order.")
        if stored_hash != params_hash:
            raise ParamsMismatch("Order params changed since preview — re-run preview_order.")
```

Run → PASS (11). Commit: `git add ibkr_mcp/core/safety/idempotency.py tests/test_idempotency.py && git commit -m "feat(safety): add IdempotencyStore + PreviewTokenStore (SQLite, TTL) (M2)"`

---

### Task 4: extend the architecture guard for `core/safety/`

**Files:**
- Modify: `tests/test_architecture.py`

The existing `test_core_never_imports_mcp_or_fastmcp` already scans `ibkr_mcp/core` recursively (`rglob`), so `core/safety/*.py` is covered. Add ONE explicit test making that coverage intentional (and guarding against the safety dir being accidentally emptied/excluded).

- [ ] **Step 1 — add test** to `tests/test_architecture.py` (append; keep existing tests untouched):

```python
SAFETY_DIR = pathlib.Path(__file__).resolve().parent.parent / "ibkr_mcp" / "core" / "safety"


def test_safety_modules_exist_and_are_scanned():
    # The recursive core/ guard above must actually cover the safety primitives.
    safety_files = {p.name for p in SAFETY_DIR.glob("*.py")}
    assert {"killswitch.py", "guardrails.py", "idempotency.py"} <= safety_files
    # And they live under CORE_DIR (so the mcp/fastmcp guard applies to them).
    assert SAFETY_DIR.is_relative_to(CORE_DIR)
```

- [ ] **Step 2 — verify** `.venv/bin/pytest tests/test_architecture.py -v` → all pass (3 tests now). Then prove safety is guarded: temporarily add `from mcp.server.fastmcp import FastMCP` to `ibkr_mcp/core/safety/killswitch.py`, run `tests/test_architecture.py`, CONFIRM `test_core_never_imports_mcp_or_fastmcp` FAILS listing killswitch.py, then REVERT and confirm clean.

- [ ] **Step 3 — commit:** `git add tests/test_architecture.py && git commit -m "test: assert core/safety is covered by the mcp-import guard (M2)"`

---

## After all tasks

- `.venv/bin/pytest -v` → expect 21 (M1) + 4 + 9 + 11 + 1 = **46 passed, 1 skipped** (report actual).
- `.venv/bin/ruff check .` clean, `.venv/bin/ruff format --check .` clean (run `ruff format .` before committing each task if needed).

## Self-review notes (author)

- **Spec coverage:** §10.6 kill-switch → Task 1; §10.1/§10.4/§10.5 paper-gate/caps/allowlist → Task 2; §10.2 preview→confirm token + §10.3 idempotency → Task 3; §14 mandatory cases — double-confirm (Task 3 `test_double_confirm_same_id_never_double_fills`), expired token (Task 3 `test_expired_token_rejected`), qty+notional caps repeatable (Task 2 `test_max_*` + `test_check_is_repeatable`), kill-switch (Task 1), allowlist (Task 2), arch guard for safety (Task 4). All covered.
- **Out of M2 scope (do NOT build):** the `preview_order`/`confirm_order` MCP tools, params-hash computation policy, rate limiting, and the GuardrailPolicy↔Config wiring — those are M3/M4.
- **No placeholders. Clock + db_path injected for determinism. stdlib only.**
