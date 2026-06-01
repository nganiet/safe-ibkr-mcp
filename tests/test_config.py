import pytest
from decimal import Decimal
from ibkr_mcp.mcp.config import Config


def test_defaults_when_env_empty():
    cfg = Config.from_env({})
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 4002  # paper by default
    assert cfg.client_id == 1
    assert cfg.read_only is True


def test_reads_env():
    cfg = Config.from_env(
        {
            "IBKR_HOST": "192.168.1.10",
            "IBKR_PORT": "4001",
            "IBKR_CLIENT_ID": "7",
            "IBKR_READ_ONLY": "false",
        }
    )
    assert cfg.host == "192.168.1.10"
    assert cfg.port == 4001
    assert cfg.client_id == 7
    assert cfg.read_only is False


def test_read_only_truthiness():
    assert Config.from_env({"IBKR_READ_ONLY": "0"}).read_only is False
    assert Config.from_env({"IBKR_READ_ONLY": "true"}).read_only is True
    assert Config.from_env({"IBKR_READ_ONLY": "1"}).read_only is True


def test_write_config_defaults():
    c = Config.from_env({})
    assert c.allow_live is False
    assert c.max_order_qty is None
    assert c.max_order_notional_usd is None
    assert c.ticker_allowlist is None


def test_write_config_parsing():
    c = Config.from_env(
        {
            "IBKR_ALLOW_LIVE": "true",
            "IBKR_MAX_ORDER_QTY": "100",
            "IBKR_MAX_ORDER_NOTIONAL_USD": "5000",
            "IBKR_TICKER_ALLOWLIST": "AAPL, MSFT",
        }
    )
    assert c.allow_live is True
    assert c.max_order_qty == Decimal("100")
    assert c.max_order_notional_usd == 5000.0
    assert c.ticker_allowlist == frozenset({"AAPL", "MSFT"})


def test_validate_refuses_writable_live_without_optin():
    # writable (read_only False) + live port + not allow_live → refuse
    cfg = Config(port=4001, read_only=False, allow_live=False)
    with pytest.raises(ValueError, match="live"):
        cfg.validate()


def test_validate_allows_readonly_on_live_port():
    Config(port=4001, read_only=True, allow_live=False).validate()  # must NOT raise


def test_validate_allows_writable_live_with_optin():
    Config(port=4001, read_only=False, allow_live=True).validate()  # must NOT raise


def test_validate_allows_writable_paper():
    Config(port=4002, read_only=False, allow_live=False).validate()  # paper port, fine
