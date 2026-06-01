"""Order & execution READS + IBKR status mapping. Imports ib_async data shapes only,
never mcp/FastMCP. Write operations (place/cancel/modify) added in M4.
"""

from datetime import datetime, timezone
from decimal import Decimal

from ib_async import LimitOrder, MarketOrder, StopOrder

from ibkr_mcp.core.contracts import qualify
from ibkr_mcp.core.models import (
    OrderConfirmation,
    OrderRequest,
    OrderStatus,
    OrderType,
    OrderUpdate,
)

_PENDING = {"PendingSubmit", "ApiPending", "PreSubmitted"}
_CANCELLED = {"Cancelled", "ApiCancelled"}


def map_ib_status(ib_status: str, filled: float, remaining: float) -> OrderStatus:
    if ib_status == "Filled":
        return OrderStatus.FILLED
    if ib_status in _CANCELLED:
        return OrderStatus.CANCELLED
    if ib_status == "Inactive":
        return OrderStatus.REJECTED
    if ib_status in _PENDING:
        return OrderStatus.PENDING
    # Submitted (or unknown active): partial if some filled while some remains.
    if filled and remaining:
        return OrderStatus.PARTIALLY_FILLED
    return OrderStatus.SUBMITTED


def _trade_to_update(t) -> OrderUpdate:
    st = t.orderStatus
    return OrderUpdate(
        # orderId is 0 for orders not from this client session (TWS-manual,
        # another client, prior session); fall back to the stable permId.
        order_id=str(t.order.orderId) if t.order.orderId else str(t.order.permId),
        status=map_ib_status(st.status, st.filled, st.remaining),
        filled_quantity=Decimal(str(st.filled)),
        fill_price=float(st.avgFillPrice) if st.avgFillPrice else None,
        timestamp=t.log[-1].time if t.log else datetime.now(timezone.utc),
        broker_order_id=str(t.order.permId) if t.order.permId else None,
        raw={"ib_status": st.status},
    )


async def get_open_orders(ib) -> list[OrderUpdate]:
    return [_trade_to_update(t) for t in await ib.reqAllOpenOrdersAsync()]


async def get_order_status(ib, order_id: str) -> OrderStatus:
    """Status of a single OPEN order by IBKR order id or perm id. Completed (filled/cancelled) orders are not returned here — use get_executions for fills."""
    for t in await ib.reqAllOpenOrdersAsync():
        ids = {str(t.order.orderId)}
        if t.order.permId:
            ids.add(str(t.order.permId))
        if order_id in ids:
            return map_ib_status(
                t.orderStatus.status, t.orderStatus.filled, t.orderStatus.remaining
            )
    raise ValueError(f"Order {order_id} not found among open orders.")


async def get_executions(ib, since: datetime) -> list[OrderUpdate]:
    """Fills at or after `since`. Note: IBKR's execution feed is effectively limited to ~the current trading day; older fills are not returned."""
    out = []
    for f in await ib.reqExecutionsAsync():
        # Real TWS may return naive execution datetimes; treat naive as UTC.
        ft = f.time if f.time.tzinfo is not None else f.time.replace(tzinfo=timezone.utc)
        if ft < since:
            continue
        out.append(
            OrderUpdate(
                order_id=str(f.execution.execId),
                status=OrderStatus.FILLED,
                filled_quantity=Decimal(str(f.execution.shares)),
                fill_price=float(f.execution.price),
                timestamp=ft,
                broker_order_id=None,
                raw={
                    "side": f.execution.side,
                    "commission": getattr(f.commissionReport, "commission", None),
                    "realized_pnl": getattr(f.commissionReport, "realizedPNL", None),
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# M4 write helpers — real IB calls, never mcp/FastMCP
# ---------------------------------------------------------------------------


def build_ib_order(req: OrderRequest):
    """Build an ib_async order object from a domain OrderRequest."""
    action = req.side.value  # "BUY" / "SELL"
    qty = float(req.quantity)
    if req.order_type == OrderType.MARKET:
        order = MarketOrder(action, qty)
    elif req.order_type == OrderType.LIMIT:
        if req.limit_price is None:
            raise ValueError("limit_price is required for a LIMIT order")
        order = LimitOrder(action, qty, req.limit_price)
    elif req.order_type == OrderType.STOP:
        if req.stop_price is None:
            raise ValueError("stop_price is required for a STOP order")
        order = StopOrder(action, qty, req.stop_price)
    else:
        raise ValueError(f"Unsupported order type: {req.order_type}")
    order.tif = req.time_in_force
    return order


async def what_if(ib, req: OrderRequest) -> dict:
    """Run a what-if (margin / commission estimate) without placing an order."""
    contract = await qualify(ib, req.symbol)
    state = await ib.whatIfOrderAsync(contract, build_ib_order(req))
    return {
        "init_margin_change": getattr(state, "initMarginChange", None),
        "maint_margin_change": getattr(state, "maintMarginChange", None),
        "commission": getattr(state, "commission", None),
        "max_commission": getattr(state, "maxCommission", None),
        "warning": getattr(state, "warningText", None),
    }


async def place_order(ib, req: OrderRequest) -> OrderConfirmation:
    """Qualify the contract and submit the order. placeOrder() is non-blocking
    (returns Trade immediately); fill events arrive asynchronously via ib_async events."""
    contract = await qualify(ib, req.symbol)
    trade = ib.placeOrder(contract, build_ib_order(req))  # sync, non-blocking
    st = trade.orderStatus
    return OrderConfirmation(
        order_id=str(trade.order.orderId or trade.order.permId or ""),
        status=map_ib_status(st.status, st.filled, st.remaining),
        filled_quantity=Decimal(str(st.filled)),
        fill_price=float(st.avgFillPrice) if st.avgFillPrice else None,
        broker_order_id=str(trade.order.permId) if trade.order.permId else None,
    )


async def cancel_order(ib, order_id: str) -> OrderConfirmation:
    """Cancel an open order by IBKR orderId or permId. Raises ValueError if not found."""
    for t in await ib.reqAllOpenOrdersAsync():
        if order_id in (str(t.order.orderId), str(t.order.permId)):
            ib.cancelOrder(t.order)
            return OrderConfirmation(
                order_id=order_id,
                status=OrderStatus.CANCELLED,
                broker_order_id=str(t.order.permId) if t.order.permId else None,
            )
    raise ValueError(f"Order {order_id} not found among open orders.")
