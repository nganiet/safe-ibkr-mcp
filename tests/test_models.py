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
