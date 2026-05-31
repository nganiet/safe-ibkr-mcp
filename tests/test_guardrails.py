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


def test_zero_or_negative_qty_rejected():
    p = _policy(max_order_qty=Decimal(100))
    for bad in (Decimal(0), Decimal(-5)):
        with pytest.raises(GuardrailViolation) as e:
            p.check_order(ticker="AAPL", qty=bad, est_price=10.0, is_paper=True)
        assert e.value.code == "INVALID_QTY"


def test_check_is_repeatable():
    p = _policy(max_order_qty=Decimal(5))
    for _ in range(3):
        with pytest.raises(GuardrailViolation):
            p.check_order(ticker="AAPL", qty=Decimal(6), est_price=1.0, is_paper=True)
