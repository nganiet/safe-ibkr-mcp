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
