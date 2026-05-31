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
        ("ApiPending", 0, 100, OrderStatus.PENDING),
        ("PendingCancel", 0, 100, OrderStatus.SUBMITTED),
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
    ib = _OrdersIB(
        [],
        fills=[
            _Fill("AAPL", "e1", old, "BOT", 10, 150.0, 1.0, 0.0),
            _Fill("AAPL", "e2", new, "BOT", 5, 151.0, 1.0, 0.0),
        ],
    )
    out = await get_executions(ib, since=datetime(2026, 5, 31, tzinfo=timezone.utc))
    assert [u.order_id for u in out] == ["e2"]
    assert out[0].filled_quantity == Decimal("5")
    assert out[0].fill_price == 151.0
    assert out[0].status == OrderStatus.FILLED


async def test_get_executions_handles_naive_fill_time():
    naive = datetime(2026, 5, 31, 12, 0)  # tz-naive (as real TWS may return)
    ib = _OrdersIB([], fills=[_Fill("AAPL", "e3", naive, "BOT", 3, 10.0, 1.0, 0.0)])
    out = await get_executions(ib, since=datetime(2026, 5, 31, tzinfo=timezone.utc))
    assert [u.order_id for u in out] == ["e3"]
    assert out[0].timestamp.tzinfo is not None


async def test_get_open_orders_handles_empty_log():
    t = _Trade(7, 900, "Submitted", 0, 100, 0.0, _TS)
    t.log = []
    out = await get_open_orders(_OrdersIB([t]))
    assert out[0].order_id == "7"
    assert out[0].timestamp is not None
