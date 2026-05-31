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
