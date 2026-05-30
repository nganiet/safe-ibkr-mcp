from mcp.server.fastmcp import FastMCP

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
