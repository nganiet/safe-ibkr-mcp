import pytest

from ibkr_mcp.core.contracts import qualify, to_ib_contract
from ibkr_mcp.core.models import AssetClass, Symbol


def test_to_ib_contract_equity_default_exchange():
    c = to_ib_contract(Symbol.equity("AAPL"))
    assert c.symbol == "AAPL"
    assert c.exchange == "SMART"
    assert c.currency == "USD"


def test_to_ib_contract_respects_explicit_exchange():
    c = to_ib_contract(Symbol(code="RY", asset_class=AssetClass.EQUITY, exchange="TSE"))
    assert c.exchange == "TSE"


def test_to_ib_contract_rejects_non_equity():
    with pytest.raises(ValueError, match="asset class"):
        to_ib_contract(Symbol(code="BTC", asset_class=AssetClass.CRYPTO))


class _FakeIB:
    def __init__(self, qualified):
        self._qualified = qualified
        self.qualified_with = None

    async def qualifyContractsAsync(self, contract):
        self.qualified_with = contract
        return self._qualified


async def test_qualify_returns_first_qualified():
    target = object()
    ib = _FakeIB([target])
    out = await qualify(ib, Symbol.equity("AAPL"))
    assert out is target


async def test_qualify_raises_when_unqualified():
    ib = _FakeIB([])
    with pytest.raises(ValueError, match="could not qualify"):
        await qualify(ib, Symbol.equity("ZZZZ"))
