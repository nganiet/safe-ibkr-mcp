from mcp.server.fastmcp import FastMCP

from ibkr_mcp.mcp.config import Config
from ibkr_mcp.mcp.server import build_server


class _FakeConn:
    is_paper = True
    ib = None

    async def ensure_connected(self):
        pass

    async def health(self):
        from ibkr_mcp.core.models import BrokerHealth

        return BrokerHealth(connected=False)


def test_build_server_returns_fastmcp_without_connecting():
    app = build_server(_FakeConn())
    assert isinstance(app, FastMCP)


async def test_registered_tool_names():
    app = build_server(_FakeConn())
    tools = await app.list_tools()
    names = {t.name for t in tools}
    assert {"ibkr_health", "get_account_summary"} <= names


async def test_readonly_config_registers_no_write_tools():
    app = build_server(_FakeConn(), Config(read_only=True))
    names = {t.name for t in await app.list_tools()}
    assert (
        "preview_order" not in names
        and "confirm_order" not in names
        and "cancel_order" not in names
    )
    assert {"ibkr_health", "get_account_summary"} <= names  # reads still there


async def test_writable_config_registers_write_tools(tmp_path):
    # state_dir=tmp_path so the writable build's stores never touch the real ~/.ibkr-mcp
    app = build_server(_FakeConn(), Config(read_only=False, port=4002, state_dir=tmp_path))
    names = {t.name for t in await app.list_tools()}
    assert {"preview_order", "confirm_order", "cancel_order"} <= names
