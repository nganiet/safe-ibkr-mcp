from decimal import Decimal

import pytest

from ibkr_mcp.core.account import get_account_summary, get_positions


class _Row:
    def __init__(self, tag, value):
        self.tag = tag
        self.value = value


class _FakeIB:
    def __init__(self, rows):
        self._rows = rows

    async def accountSummaryAsync(self, account=""):
        return self._rows


@pytest.fixture
def rows():
    return [
        _Row("NetLiquidation", "100000"),
        _Row("TotalCashValue", "50000"),
        _Row("BuyingPower", "200000"),
        _Row("GrossPositionValue", "50000"),
        _Row("UnrealizedPnL", "1234.5"),
        _Row("SomethingElse", "ignored"),
    ]


async def test_maps_known_tags(rows):
    acct = await get_account_summary(_FakeIB(rows))
    assert acct.total_value == 100000.0
    assert acct.cash == 50000.0
    assert acct.buying_power == 200000.0
    assert acct.positions_value == 50000.0
    assert acct.unrealized_pnl == 1234.5


async def test_missing_tag_defaults_to_zero():
    acct = await get_account_summary(_FakeIB([_Row("NetLiquidation", "10")]))
    assert acct.total_value == 10.0
    assert acct.cash == 0.0
    assert acct.buying_power == 0.0


async def test_non_numeric_value_defaults_to_zero():
    acct = await get_account_summary(_FakeIB([_Row("NetLiquidation", "N/A")]))
    assert acct.total_value == 0.0


class _FakeContract:
    def __init__(self, symbol):
        self.symbol = symbol


class _FakePosition:
    def __init__(self, symbol, position, avg_cost):
        self.contract = _FakeContract(symbol)
        self.position = position
        self.avgCost = avg_cost


class _FakePosIB:
    def __init__(self, positions):
        self._positions = positions

    def positions(self):
        return self._positions


async def test_get_positions_maps_shares_and_cost():
    ib = _FakePosIB([_FakePosition("AAPL", 10, 150.0), _FakePosition("MSFT", 5, 300.0)])
    out = await get_positions(ib)
    assert [p.ticker for p in out] == ["AAPL", "MSFT"]
    assert out[0].shares == Decimal("10")
    assert out[0].avg_cost == 150.0
    # live valuation is M3b — unavailable fields are 0.0 in M3a
    assert out[0].current_price == 0.0
    assert out[0].market_value == 0.0
    assert out[0].unrealized_pnl == 0.0


async def test_get_positions_empty():
    assert await get_positions(_FakePosIB([])) == []


class _CashRow:
    def __init__(self, tag, value, currency):
        self.tag = tag
        self.value = value
        self.currency = currency


class _FakeCashIB:
    def __init__(self, values, *, accounts=("DU123",)):
        self._values = values
        self._accounts = list(accounts)
        self.subscribed = False

    def accountValues(self):
        return self._values

    def managedAccounts(self):
        return self._accounts

    async def reqAccountUpdatesAsync(self, account):
        self.subscribed = True


async def test_cash_balances_maps_per_currency():
    from ibkr_mcp.core.account import get_cash_balances

    ib = _FakeCashIB(
        [
            _CashRow("CashBalance", "472.00", "CAD"),
            _CashRow("CashBalance", "760.99", "USD"),
            _CashRow("CashBalance", "1536.55", "BASE"),
            _CashRow("ExchangeRate", "1.3989", "USD"),  # ignored — not CashBalance
        ]
    )
    out = await get_cash_balances(ib)
    assert {(c.currency, c.amount) for c in out} == {
        ("CAD", 472.00),
        ("USD", 760.99),
        ("BASE", 1536.55),
    }
    assert ib.subscribed is False  # ledger already populated → no re-subscribe


async def test_cash_balances_subscribes_when_empty():
    from ibkr_mcp.core.account import get_cash_balances

    class _LazyIB(_FakeCashIB):
        def accountValues(self):
            return self._values if self.subscribed else []

    ib = _LazyIB([_CashRow("CashBalance", "100", "USD")])
    out = await get_cash_balances(ib)
    assert ib.subscribed is True
    assert [(c.currency, c.amount) for c in out] == [("USD", 100.0)]


async def test_cash_balances_skips_bad_values():
    from ibkr_mcp.core.account import get_cash_balances

    ib = _FakeCashIB(
        [
            _CashRow("CashBalance", "N/A", "USD"),
            _CashRow("CashBalance", "5", "CAD"),
        ]
    )
    out = await get_cash_balances(ib)
    assert [(c.currency, c.amount) for c in out] == [("CAD", 5.0)]
