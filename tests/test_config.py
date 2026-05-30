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
