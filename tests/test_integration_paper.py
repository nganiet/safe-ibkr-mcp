"""Real paper-Gateway round-trip. Requires a logged-in IB paper Gateway on port 4002.

Run explicitly:  IBKR_MCP_RUN_INTEGRATION=1 pytest -m integration -v
"""

import os

import pytest

from ibkr_mcp.core.connection import IBKRConnection
from ibkr_mcp.mcp import tools_read

pytestmark = pytest.mark.integration

_RUN = os.environ.get("IBKR_MCP_RUN_INTEGRATION") == "1"


@pytest.mark.skipif(not _RUN, reason="set IBKR_MCP_RUN_INTEGRATION=1 with a paper Gateway running")
async def test_health_and_account_against_paper():
    conn = IBKRConnection("127.0.0.1", 4002, 99, readonly=True)
    try:
        await conn.ensure_connected()
        health = await tools_read.health(conn)
        assert health["connected"] is True
        assert health["is_paper"] is True

        acct = await tools_read.account_summary(conn)
        # A funded paper account reports a positive net liquidation value.
        assert acct["total_value"] > 0
        print("PAPER ACCOUNT SUMMARY:", acct)
    finally:
        conn.disconnect()
