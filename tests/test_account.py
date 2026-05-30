import pytest

from ibkr_mcp.core.account import get_account_summary


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
