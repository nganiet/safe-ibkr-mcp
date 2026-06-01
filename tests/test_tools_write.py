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


_ORDER = {
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "quantity": "10",
    "limit_price": 150.0,
}


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
        return OrderConfirmation(
            order_id="555", status=OrderStatus.SUBMITTED, broker_order_id="555"
        )

    monkeypatch.setattr(tools_write, "place_order", fake_place)

    prev = await tools_write.preview_order(_Conn(), ctx, **_ORDER)
    assert "confirm_token" in prev and prev["confirm_token"]

    conf1 = await tools_write.confirm_order(
        _Conn(), ctx, confirm_token=prev["confirm_token"], client_order_id="cli-1"
    )
    assert conf1["status"] == "SUBMITTED"
    # MONEY-CRITICAL retry: same client_order_id → cached result, NO second placement, NO UnknownToken
    conf2 = await tools_write.confirm_order(
        _Conn(), ctx, confirm_token=prev["confirm_token"], client_order_id="cli-1"
    )
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
        await tools_write.confirm_order(
            _Conn(is_paper=False), ctx, confirm_token=tok, client_order_id="cli-3"
        )
    assert e.value.code == "LIVE_NOT_ALLOWED"


async def _fake_what_if(ib, req):
    return {"init_margin_change": "1500", "commission": 1.0}


async def _fail_if_called(*a, **k):
    raise AssertionError("must not be called")
