from ibkr_mcp.core.connection import IBKRConnection


class _FakeIB:
    def __init__(self):
        self._connected = False
        self.connect_calls = []

    def isConnected(self):
        return self._connected

    async def connectAsync(self, host, port, clientId, readonly=False, **kwargs):
        self.connect_calls.append((host, port, clientId, readonly))
        self._connected = True

    def disconnect(self):
        self._connected = False
        return None


def _make(port=4002, readonly=True):
    fake = _FakeIB()
    conn = IBKRConnection("127.0.0.1", port, 1, readonly=readonly, ib_factory=lambda: fake)
    return conn, fake


def test_is_paper_for_paper_ports():
    conn, _ = _make(port=4002)
    assert conn.is_paper is True
    conn2, _ = _make(port=4001)
    assert conn2.is_paper is False
    conn3, _ = _make(port=7497)
    assert conn3.is_paper is True
    conn4, _ = _make(port=7496)
    assert conn4.is_paper is False


async def test_health_reflects_connection_state():
    conn, fake = _make()
    h = await conn.health()
    assert h.connected is False
    assert h.last_heartbeat_at is None

    await conn.ensure_connected()
    h2 = await conn.health()
    assert h2.connected is True
    assert h2.last_heartbeat_at is not None


async def test_ensure_connected_connects_once():
    conn, fake = _make(port=4002, readonly=True)
    await conn.ensure_connected()
    assert fake.connect_calls == [("127.0.0.1", 4002, 1, True)]
    await conn.ensure_connected()
    assert len(fake.connect_calls) == 1


def test_disconnect_is_safe_when_not_connected():
    conn, fake = _make()
    conn.disconnect()
    assert fake.isConnected() is False


async def test_disconnect_closes_a_live_connection():
    conn, fake = _make()
    await conn.ensure_connected()
    assert fake.isConnected() is True
    conn.disconnect()
    assert fake.isConnected() is False
