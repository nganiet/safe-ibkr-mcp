from datetime import datetime, timezone
from decimal import Decimal

from ibkr_mcp.core.models import (
    AccountInfo,
    AssetClass,
    BrokerHealth,
    OrderStatus,
    OrderUpdate,
    PositionInfo,
    Symbol,
)
from ibkr_mcp.core.models import OrderConfirmation, OrderRequest, OrderSide, OrderType


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
    assert a.cash == 50_000.0
    assert a.positions_value == 50_000.0


def test_symbol_equity_shortcut():
    s = Symbol.equity("aapl")
    assert s.code == "AAPL"
    assert s.asset_class == AssetClass.EQUITY
    assert s.exchange is None


def test_order_status_values():
    assert OrderStatus.FILLED == "FILLED"
    assert OrderStatus.PARTIALLY_FILLED == "PARTIALLY_FILLED"


def test_position_info_fields():
    p = PositionInfo(
        ticker="AAPL",
        shares=Decimal(10),
        avg_cost=150.0,
        current_price=0.0,
        unrealized_pnl=0.0,
        market_value=0.0,
    )
    assert p.ticker == "AAPL"
    assert p.shares == Decimal(10)


def test_order_update_defaults():
    from datetime import datetime, timezone

    u = OrderUpdate(
        order_id="1",
        status=OrderStatus.SUBMITTED,
        filled_quantity=Decimal(0),
        fill_price=None,
        timestamp=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )
    assert u.broker_order_id is None
    assert u.raw == {}


def test_order_request_ticker_shortcut():
    r = OrderRequest(
        symbol=Symbol.equity("AAPL"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(10),
    )
    assert r.ticker == "AAPL"
    assert r.limit_price is None and r.stop_price is None


def test_order_confirmation_defaults():
    c = OrderConfirmation(order_id="1", status=OrderStatus.SUBMITTED)
    assert c.broker_order_id is None and c.reject_reason is None
    assert c.filled_quantity == Decimal(0)
