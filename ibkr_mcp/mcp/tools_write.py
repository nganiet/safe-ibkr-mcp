"""Write-tool orchestration — preview -> confirm. FastMCP-free for testability.

Wires the M2 safety primitives into the order path. NEVER imports ib_async
(goes through ibkr_mcp.core). The build_server layer registers these tools ONLY
when the server is writable (read_only=False).
"""

from dataclasses import dataclass
from decimal import Decimal

from ibkr_mcp.core.models import OrderRequest, OrderSide, OrderType, Symbol
from ibkr_mcp.core.orders import cancel_order, place_order, what_if
from ibkr_mcp.core.safety.guardrails import GuardrailPolicy
from ibkr_mcp.core.safety.idempotency import IdempotencyStore, PreviewTokenStore
from ibkr_mcp.core.safety.killswitch import KillSwitch


@dataclass
class WriteContext:
    policy: GuardrailPolicy
    killswitch: KillSwitch
    idempotency: IdempotencyStore
    tokens: PreviewTokenStore


def _req_from_payload(p: dict) -> OrderRequest:
    return OrderRequest(
        symbol=Symbol.equity(p["symbol"]),
        side=OrderSide(p["side"]),
        order_type=OrderType(p["order_type"]),
        quantity=Decimal(str(p["quantity"])),
        limit_price=p.get("limit_price"),
        stop_price=p.get("stop_price"),
    )


def _est_price(p: dict) -> float | None:
    # Notional cap needs a price; use the limit price when present (market orders
    # have no pre-trade price until M3b live quotes — notional check then skipped).
    return p.get("limit_price") or p.get("stop_price")


async def preview_order(conn, ctx: WriteContext, **payload) -> dict:
    await conn.ensure_connected()
    req = _req_from_payload(payload)
    # Guardrails BEFORE issuing a token — a capped/disallowed order never previews.
    ctx.policy.check_order(
        ticker=req.ticker,
        qty=req.quantity,
        est_price=_est_price(payload),
        is_paper=conn.is_paper,
    )
    impact = await what_if(conn.ib, req)
    token = ctx.tokens.issue(payload)
    return {
        "preview": {"order": payload, "impact": impact},
        "confirm_token": token,
        "expires_in_seconds": 60,
    }


async def confirm_order(conn, ctx: WriteContext, *, confirm_token: str) -> dict:
    await conn.ensure_connected()
    # Idempotency keyed on the single-use token: collision-proof and retry-safe.
    # (The token stays a valid idempotency key even after it's consumed from the token store.)
    cached = ctx.idempotency.get(confirm_token)
    if cached is not None:
        return cached
    payload = ctx.tokens.consume(confirm_token)  # single-use; raises if expired/unknown
    req = _req_from_payload(payload)
    ctx.killswitch.check()
    ctx.policy.check_order(
        ticker=req.ticker,
        qty=req.quantity,
        est_price=_est_price(payload),
        is_paper=conn.is_paper,
    )
    conf = await place_order(conn.ib, req)
    result = {
        "order_id": conf.order_id,
        "status": conf.status.value,
        "broker_order_id": conf.broker_order_id,
        "reject_reason": conf.reject_reason,
    }
    ctx.idempotency.remember(confirm_token, result)
    return result


async def cancel_order_tool(conn, ctx: WriteContext, *, order_id: str) -> dict:
    await conn.ensure_connected()
    ctx.killswitch.check()
    conf = await cancel_order(conn.ib, order_id)
    return {
        "order_id": conf.order_id,
        "status": conf.status.value,
        "broker_order_id": conf.broker_order_id,
    }
