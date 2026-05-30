# ibkr-mcp (working name)

Guarded Interactive Brokers MCP server. Paper-trading by default. **Not financial advice.**

## Run the M1 skeleton against a paper Gateway

1. Start IB Gateway / TWS logged into your **paper** account, API enabled, port 4002.
2. `pip install -e ".[dev]"`
3. `IBKR_PORT=4002 python -m ibkr_mcp` (or add to your MCP client config).

See `docs/` for the design and plans.
