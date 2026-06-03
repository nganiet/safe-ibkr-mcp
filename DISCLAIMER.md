# Disclaimer

**This software is not financial advice. Use it at your own risk.**

This project exposes an [Interactive Brokers](https://www.interactivebrokers.com/)
account to AI agents through the Model Context Protocol. Placing orders moves
**real money**. Read this before connecting it to a live account.

## No warranty

The software is provided "as is", without warranty of any kind, as stated in
[`LICENSE`](./LICENSE). The authors and contributors are **not liable** for any
financial loss, missed trade, erroneous order, data error, or any other damage
arising from the use of this software.

## Not financial advice

Nothing produced by this server — quotes, account data, order previews — is a
recommendation to buy, sell, or hold any security. You are solely responsible
for every order you confirm.

## The safety model reduces risk; it does not remove it

This server enforces guardrails (paper-by-default, two-step
`preview_order` → `confirm_order` with a single-use token, idempotency to prevent
duplicate fills, size/notional caps, ticker allowlist, kill switch). These are
**defense in depth, not a guarantee.** They cannot protect you from:

- a market that moves against you,
- a bug in this software or in its dependencies,
- a misconfigured cap, allowlist, or account,
- an LLM that confirms an order you did not intend,
- exchange, broker, connectivity, or data outages.

> A dollar **notional cap only applies when a price is known** (limit/stop orders).
> A plain **market order has no pre-trade price and can bypass the notional cap.**
> Prefer limit orders when you want a hard spending ceiling.

## Test in paper first

**Always validate against an IBKR paper-trading account before touching a live
account.** Run with `IBKR_READ_ONLY=true` until you have verified the behaviour
you expect. A writable server refuses to start against a live port unless you
explicitly set `IBKR_ALLOW_LIVE=true` — that opt-in exists so live trading is
always a deliberate choice.

## Your responsibility

You are responsible for compliance with your local laws and regulations, with
Interactive Brokers' terms of service and API agreements, and for any market
data entitlements your account requires. You bring your own IB Gateway / TWS and
your own credentials; this project never handles your login or 2FA.

By using this software you accept full responsibility for all resulting trades
and their outcomes.
