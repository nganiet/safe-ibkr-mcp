"""SQLite-backed write-time safety state (~/.ibkr-mcp/state.db).

Two cohesive concerns over one state file:
- IdempotencyStore: client_order_id -> result, so a retried confirm never double-fills.
- PreviewTokenStore: opaque single-use preview tokens bound to a params hash, with TTL.
Pure logic — no ib_async, no mcp.
"""

import contextlib
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
        with contextlib.closing(_connect(self._db)) as c, c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS idempotency "
                "(client_order_id TEXT PRIMARY KEY, result TEXT NOT NULL)"
            )

    def get(self, client_order_id: str) -> dict | None:
        with contextlib.closing(_connect(self._db)) as c, c:
            row = c.execute(
                "SELECT result FROM idempotency WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        return json.loads(row[0]) if row is not None else None

    def remember(self, client_order_id: str, result: dict) -> None:
        # INSERT OR IGNORE keeps the FIRST result (idempotent).
        with contextlib.closing(_connect(self._db)) as c, c:
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
        with contextlib.closing(_connect(self._db)) as c, c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS preview_tokens "
                "(token TEXT PRIMARY KEY, params_hash TEXT NOT NULL, created_at TEXT NOT NULL)"
            )

    def issue(self, params_hash: str) -> str:
        token = secrets.token_urlsafe(24)
        with contextlib.closing(_connect(self._db)) as c, c:
            c.execute(
                "INSERT INTO preview_tokens (token, params_hash, created_at) VALUES (?, ?, ?)",
                (token, params_hash, self._now().isoformat()),
            )
        return token

    def consume(self, token: str, params_hash: str, *, ttl_seconds: int = 60) -> None:
        with contextlib.closing(_connect(self._db)) as c, c:
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
