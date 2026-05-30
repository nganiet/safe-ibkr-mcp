from datetime import datetime, timezone

from ibkr_mcp.core.models import BrokerHealth
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
