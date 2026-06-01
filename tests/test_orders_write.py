from decimal import Decimal

import pytest

from ibkr_mcp.core.models import (
    OrderConfirmation,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Symbol,
)
from ibkr_mcp.core.orders import build_ib_order, cancel_order, place_order, what_if


def _req(order_type=OrderType.LIMIT, qty=10, limit=150.0, stop=None, side=OrderSide.BUY):
    return OrderRequest(
        symbol=Symbol.equity("AAPL"),
        side=side,
        order_type=order_type,
        quantity=Decimal(qty),
        limit_price=limit,
        stop_price=stop,
    )


def test_build_ib_order_limit():
    o = build_ib_order(_req(OrderType.LIMIT, 10, 150.0))
    assert o.action == "BUY" and o.totalQuantity == 10 and o.lmtPrice == 150.0
    assert o.orderType == "LMT"
    assert o.tif == "DAY"


def test_build_ib_order_market():
    o = build_ib_order(_req(OrderType.MARKET, 5, None, side=OrderSide.SELL))
    assert o.action == "SELL" and o.totalQuantity == 5 and o.orderType == "MKT"


def test_build_ib_order_stop():
    o = build_ib_order(_req(OrderType.STOP, 5, None, stop=140.0))
    assert o.orderType == "STP" and o.auxPrice == 140.0


def test_build_ib_order_limit_requires_price():
    with pytest.raises(ValueError, match="limit_price"):
        build_ib_order(_req(OrderType.LIMIT, 10, None))


def test_build_ib_order_stop_limit_unsupported():
    with pytest.raises(ValueError, match="Unsupported"):
        build_ib_order(_req(OrderType.STOP_LIMIT, 5, 150.0, stop=140.0))


class _Trade:
    def __init__(self):
        self.order = type("O", (), {"orderId": 42, "permId": 0})()
        self.orderStatus = type(
            "S",
            (),
            {"status": "Submitted", "filled": 0, "remaining": 10, "avgFillPrice": 0.0},
        )()


class _PlaceIB:
    def __init__(self):
        self.placed = None

    async def qualifyContractsAsync(self, contract):
        return [contract]

    def placeOrder(self, contract, order):
        self.placed = (contract, order)
        return _Trade()

    async def whatIfOrderAsync(self, contract, order):
        return type(
            "OS",
            (),
            {
                "initMarginChange": "1500",
                "commission": 1.0,
                "maxCommission": 1.0,
                "minCommission": 1.0,
            },
        )()


async def test_place_order_returns_submitted_confirmation():
    ib = _PlaceIB()
    conf = await place_order(ib, _req())
    assert isinstance(conf, OrderConfirmation)
    assert conf.status == OrderStatus.SUBMITTED
    assert conf.order_id == "42"
    assert conf.broker_order_id is None  # permId 0 → None
    assert ib.placed is not None  # actually called placeOrder


async def test_what_if_returns_margin_commission():
    ib = _PlaceIB()
    out = await what_if(ib, _req())
    assert "init_margin_change" in out
    assert out["commission"] == 1.0


# cancel_order tests


class _CancelOrder:
    def __init__(self):
        self.order = type("O", (), {"orderId": 42, "permId": 555})()

    @property
    def orderStatus(self):
        return type("S", (), {"status": "Submitted", "filled": 0, "remaining": 10})()


class _CancelIB:
    def __init__(self, trades):
        self._trades = trades
        self.cancelled = []

    async def reqAllOpenOrdersAsync(self):
        return self._trades

    def cancelOrder(self, order):
        self.cancelled.append(order)


async def test_cancel_order_found_by_order_id():
    trade = _CancelOrder()
    ib = _CancelIB([trade])
    conf = await cancel_order(ib, "42")
    assert conf.status == OrderStatus.CANCELLED
    assert conf.broker_order_id == "555"
    assert len(ib.cancelled) == 1


async def test_cancel_order_found_by_perm_id():
    trade = _CancelOrder()
    ib = _CancelIB([trade])
    conf = await cancel_order(ib, "555")
    assert conf.status == OrderStatus.CANCELLED
    assert conf.order_id == "555"


async def test_cancel_order_not_found_raises():
    ib = _CancelIB([])
    with pytest.raises(ValueError, match="not found"):
        await cancel_order(ib, "999")
