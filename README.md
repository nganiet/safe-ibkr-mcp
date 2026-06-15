# ibkr-mcp-guarded

**A guarded [Interactive Brokers](https://www.interactivebrokers.com/) MCP server — safe LLM trading access.**

Exposes your Interactive Brokers account to any [Model Context Protocol](https://modelcontextprotocol.io)
client (Claude Desktop, Claude Code, Cursor, …) — with **execution safety wired into the server itself**,
not left to a client that might auto-approve everything.

> ⚠️ **Paper-trading by default. Not financial advice. Placing orders moves real money.**
> Read [`DISCLAIMER.md`](./DISCLAIMER.md) before connecting this to a live account.

- **Python:** 3.11 / 3.12 · **License:** MIT · **Transport:** stdio · **Engine:** [`ib_async`](https://github.com/ib-api-reloaded/ib_async)

---

## Why another IBKR MCP server?

Several IBKR MCP servers already exist. The differentiator here is **auditable, server-enforced safety**:
the guardrails hold even if the MCP client auto-approves every tool call. A read-only build cannot place
an order *by construction* — the write tools are not even registered.

## Safety model

| Guardrail | Behaviour |
|---|---|
| **Paper by default** | Defaults to the paper port. A *writable* server **refuses to start** on a live port unless you set `IBKR_ALLOW_LIVE=true`. |
| **Two-step orders** | `preview_order` validates + estimates margin/commission and returns a **single-use token** (60 s TTL). It **places nothing**. Only `confirm_order(token)` places. |
| **Idempotency** | Confirmation is keyed on the single-use token, so a retried `confirm_order` returns the original result and **never double-places**. |
| **Checked at both steps** | Guardrails (live gate, allowlist, qty cap, notional cap) are re-checked at **both** preview and confirm; the **kill switch** is enforced at **confirm** — the moment an order is actually placed. |
| **Size & notional caps** | `IBKR_MAX_ORDER_QTY` and `IBKR_MAX_ORDER_NOTIONAL_USD` reject oversized orders. |
| **Ticker allowlist** | `IBKR_TICKER_ALLOWLIST` restricts which symbols can be traded. |
| **Kill switch** | `touch ~/.ibkr-mcp/KILL` freezes all writes instantly, without restarting the process. |
| **Read-only build** | With `IBKR_READ_ONLY=true` (the default) the write tools are **never registered**. |

> **Caveat — caps need a price.** A dollar notional cap can only be enforced when a price is known, i.e.
> for **limit/stop** orders. A plain **market order has no pre-trade price and bypasses the notional cap.**
> Use limit orders when you want a hard spending ceiling.

## Requirements

- **Python 3.11 or 3.12** (pinned: `ib_async`'s `nest_asyncio` dependency is broken on 3.13/3.14).
- Your **own** IB Gateway or TWS, logged in (paper or live) with the API enabled. This server is
  *Bring-Your-Own-Gateway*: it never handles your login or 2FA.
- Default API ports: **paper** `4002` (Gateway) / `7497` (TWS) · **live** `4001` (Gateway) / `7496` (TWS).

## Install

```bash
uvx ibkr-mcp-guarded        # zero-install run (recommended)
# or
pip install ibkr-mcp-guarded
```

## Quickstart (read-only, paper)

1. Start IB Gateway / TWS logged into your **paper** account, API enabled, port `4002`.
2. Run it read-only:
   ```bash
   IBKR_PORT=4002 IBKR_READ_ONLY=true uvx ibkr-mcp-guarded
   ```
3. Add it to your MCP client. Example (`claude_desktop_config.json` / `.mcp.json`):
   ```json
   {
     "mcpServers": {
       "ibkr": {
         "command": "uvx",
         "args": ["ibkr-mcp-guarded"],
         "env": { "IBKR_PORT": "4002", "IBKR_READ_ONLY": "true" }
       }
     }
   }
   ```

## Configuration

All configuration is via environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `IBKR_HOST` | `127.0.0.1` | Gateway/TWS host. |
| `IBKR_PORT` | `4002` | API port (see ports above). |
| `IBKR_CLIENT_ID` | `1` | API client id (use a distinct one per concurrent connection). |
| `IBKR_READ_ONLY` | `true` | `true` → no write tools registered. Set `false` to enable trading. |
| `IBKR_ALLOW_LIVE` | `false` | Required (`true`) to run a **writable** server on a **live** port. |
| `IBKR_MAX_ORDER_QTY` | — | Max shares per order. |
| `IBKR_MAX_ORDER_NOTIONAL_USD` | — | Max order value in USD (limit/stop orders only — see caveat). |
| `IBKR_TICKER_ALLOWLIST` | — | Comma-separated symbols, e.g. `AAPL,MSFT`. |
| `IBKR_STATE_DIR` | `~/.ibkr-mcp` | Where the token/idempotency DB and `KILL` file live. |

## Tools

**Read tools** (always available):

| Tool | Purpose |
|---|---|
| `ibkr_health` | Connection state: connected, paper vs live, last heartbeat. |
| `get_account_summary` | Net liquidation, cash, buying power, positions value, unrealized P&L, base currency. |
| `get_cash_balances` | Cash per currency (e.g. USD, CAD) plus the consolidated BASE row — surfaces a multi-currency split that the base-currency summary hides. |
| `get_positions` | Open positions (ticker, shares, avg cost). |
| `get_open_orders` | Currently open orders with status and fill progress. |
| `get_order_status` | Status of a single open order by order id / perm id. |
| `get_executions` | Fills since an ISO-8601 timestamp. |
| `get_quote` | Snapshot quote (last/bid/ask/close). Delayed by default (free). |
| `get_historical_bars` | Historical OHLCV bars. |
| `get_option_chain` | Option expirations and strikes (SMART). |

**Write tools** (only when `IBKR_READ_ONLY=false`):

| Tool | Purpose |
|---|---|
| `preview_order` | Validate against guardrails, estimate margin/commission, return a `confirm_token`. Places nothing. |
| `confirm_order` | Place the previewed order. Single-use + idempotent. |
| `cancel_order` | Cancel an open order by order id / perm id. |

## Enabling writes (deliberately)

Set `IBKR_READ_ONLY=false`. On a **live** port you must *also* set `IBKR_ALLOW_LIVE=true`, otherwise the
server refuses to start — live trading is always an explicit choice. Set caps and an allowlist as well:

```bash
IBKR_PORT=4002 \
IBKR_READ_ONLY=false \
IBKR_MAX_ORDER_QTY=10 \
IBKR_MAX_ORDER_NOTIONAL_USD=2000 \
IBKR_TICKER_ALLOWLIST=AAPL,MSFT,NVDA \
uvx ibkr-mcp-guarded
```

Order flow: `preview_order(...)` → returns impact + `confirm_token` (TTL 60 s, places nothing) →
`confirm_order(confirm_token)` places exactly once → `cancel_order(order_id)` if needed.
Freeze everything at any moment with `touch ~/.ibkr-mcp/KILL`.

## Architecture

```
ibkr_mcp/
  core/   # imports ib_async, never mcp  — the extractable engine
  mcp/    # imports mcp,  never ib_async — the thin tool layer
```

The `core ↛ mcp` and `mcp ↛ ib_async` seams are enforced by tests, so `core/` can later ship as a
standalone package without a rewrite.

## Development

```bash
pip install -e ".[dev]"
pytest                       # unit tests (paper-integration tests are gated)
ruff check . && ruff format --check .
```

## Disclaimer & License

This software is **not financial advice** and comes with **no warranty**. See [`DISCLAIMER.md`](./DISCLAIMER.md).
Licensed under the [MIT License](./LICENSE).
