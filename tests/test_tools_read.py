from datetime import datetime, timezone
from decimal import Decimal

from ibkr_mcp.core.models import BrokerHealth, OrderStatus, OrderUpdate
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
    assert isinstance(out["last_heartbeat_at"], str)
    assert out["last_heartbeat_at"].endswith("+00:00")  # ISO 8601, tz-aware


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
    assert out["positions_value"] == 0.0
    assert out["unrealized_pnl"] == 0.0
    # base_currency present (empty when the rows carry no currency); the cash split is
    # absent here because _FakeAcctIB has no accountValues() (guarded fetch degrades).
    assert out["base_currency"] == ""
    assert "cash_by_currency" not in out


class _CcyRow:
    def __init__(self, tag, value, currency):
        self.tag, self.value, self.currency = tag, value, currency


class _MultiCcyIB:
    def __init__(self, summary, values):
        self._summary, self._values = summary, values

    async def accountSummaryAsync(self, account=""):
        return self._summary

    def accountValues(self):
        return self._values

    def managedAccounts(self):
        return ["DU1"]

    async def reqAccountUpdatesAsync(self, account):  # not reached — values populated
        pass


class _ConnWith:
    def __init__(self, ib):
        self.ib = ib

    async def ensure_connected(self):
        pass


async def test_account_summary_surfaces_base_currency_and_multi_currency():
    ib = _MultiCcyIB(
        summary=[
            _CcyRow("NetLiquidation", "4006.06", "CAD"),
            _CcyRow("TotalCashValue", "1536.55", "CAD"),
            _CcyRow("GrossPositionValue", "2461.92", "CAD"),
        ],
        values=[
            _CcyRow("CashBalance", "472.00", "CAD"),
            _CcyRow("CashBalance", "760.99", "USD"),
            _CcyRow("CashBalance", "1536.55", "BASE"),  # consolidated → excluded
        ],
    )
    out = await tools_read.account_summary(_ConnWith(ib))
    assert out["base_currency"] == "CAD"
    assert out["cash_by_currency"] == {"CAD": 472.00, "USD": 760.99}
    assert out["multi_currency"] is True


async def test_account_summary_single_currency_flag_false():
    ib = _MultiCcyIB(
        summary=[_CcyRow("NetLiquidation", "2000", "USD")],
        values=[
            _CcyRow("CashBalance", "2000", "USD"),
            _CcyRow("CashBalance", "0", "CAD"),  # zero balance → not counted as multi
        ],
    )
    out = await tools_read.account_summary(_ConnWith(ib))
    assert out["base_currency"] == "USD"
    assert out["multi_currency"] is False


class _ReadsConn:
    is_paper = True

    def __init__(self):
        self.ensured = False

    async def ensure_connected(self):
        self.ensured = True

    @property
    def ib(self):
        return self._ib


class _FakePos:
    def __init__(self, symbol, position, avg_cost):
        self.contract = type("C", (), {"symbol": symbol})()
        self.position = position
        self.avgCost = avg_cost


class _PosIB:
    def positions(self):
        return [_FakePos("AAPL", 10, 150.0)]


async def test_positions_tool():
    conn = _ReadsConn()
    conn._ib = _PosIB()
    out = await tools_read.positions(conn)
    assert conn.ensured is True
    assert out[0]["ticker"] == "AAPL"
    assert out[0]["shares"] == "10"  # Decimal serialized as str
    assert out[0]["valuation_available"] is False


async def test_open_orders_tool(monkeypatch):
    conn = _ReadsConn()
    updates = [
        OrderUpdate(
            "7",
            OrderStatus.SUBMITTED,
            Decimal(0),
            None,
            datetime(2026, 5, 31, tzinfo=timezone.utc),
            broker_order_id="900",
        )
    ]

    async def fake_get_open_orders(ib):
        return updates

    monkeypatch.setattr(tools_read, "get_open_orders", fake_get_open_orders)
    conn._ib = object()
    out = await tools_read.open_orders(conn)
    assert conn.ensured is True
    assert out[0]["order_id"] == "7"
    assert out[0]["status"] == "SUBMITTED"
    assert out[0]["broker_order_id"] == "900"


async def test_order_status_tool(monkeypatch):
    conn = _ReadsConn()

    async def fake_status(ib, order_id):
        return OrderStatus.FILLED

    monkeypatch.setattr(tools_read, "get_order_status", fake_status)
    conn._ib = object()
    out = await tools_read.order_status(conn, "7")
    assert out == {"order_id": "7", "status": "FILLED"}


async def test_executions_tool(monkeypatch):
    conn = _ReadsConn()
    upd = [
        OrderUpdate(
            "e1", OrderStatus.FILLED, Decimal(5), 151.0, datetime(2026, 5, 31, tzinfo=timezone.utc)
        )
    ]

    async def fake_execs(ib, since):
        return upd

    monkeypatch.setattr(tools_read, "get_executions", fake_execs)
    conn._ib = object()
    out = await tools_read.executions(conn, since_iso="2026-05-31T00:00:00+00:00")
    assert out[0]["order_id"] == "e1"
    assert out[0]["filled_quantity"] == "5"


async def test_executions_tool_normalizes_naive_since(monkeypatch):
    conn = _ReadsConn()
    captured = {}

    async def fake_execs(ib, since):
        captured["since"] = since
        return []

    monkeypatch.setattr(tools_read, "get_executions", fake_execs)
    conn._ib = object()
    await tools_read.executions(conn, since_iso="2026-05-31T00:00:00")  # naive ISO
    assert captured["since"].tzinfo is not None


async def test_quote_tool(monkeypatch):
    conn = _ReadsConn()
    conn._ib = object()

    async def fake_get_quote(ib, symbol, *, delayed=True):
        assert symbol.code == "AAPL"
        return {"ticker": "AAPL", "last": 150.5, "delayed": delayed}

    monkeypatch.setattr(tools_read, "get_quote", fake_get_quote)
    out = await tools_read.quote(conn, "aapl")
    assert conn.ensured is True
    assert out["ticker"] == "AAPL" and out["last"] == 150.5


async def test_historical_bars_tool(monkeypatch):
    conn = _ReadsConn()
    conn._ib = object()

    async def fake_bars(ib, symbol, **kw):
        return [{"date": "2026-05-31", "close": 2.0}]

    monkeypatch.setattr(tools_read, "get_historical_bars", fake_bars)
    out = await tools_read.historical_bars(conn, "AAPL", duration="1 D", bar_size="1 hour")
    assert out[0]["close"] == 2.0


async def test_option_chain_tool(monkeypatch):
    conn = _ReadsConn()
    conn._ib = object()

    async def fake_chain(ib, symbol):
        return {"ticker": "AAPL", "expirations": ["20260619"]}

    monkeypatch.setattr(tools_read, "get_option_chain", fake_chain)
    out = await tools_read.option_chain(conn, "AAPL")
    assert out["expirations"] == ["20260619"]
