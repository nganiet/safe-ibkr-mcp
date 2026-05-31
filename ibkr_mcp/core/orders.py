"""Order & execution READS + IBKR status mapping. Imports ib_async data shapes only,
never mcp/FastMCP. Write operations (place/cancel/modify) are M4.
"""

from datetime import datetime
from decimal import Decimal

from ibkr_mcp.core.models import OrderStatus, OrderUpdate

_PENDING = {"PendingSubmit", "ApiPending", "PreSubmitted", "PendingCancel"}
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
        order_id=str(t.order.orderId),
        status=map_ib_status(st.status, st.filled, st.remaining),
        filled_quantity=Decimal(str(st.filled)),
        fill_price=float(st.avgFillPrice) if st.avgFillPrice else None,
        timestamp=t.log[-1].time,
        broker_order_id=str(t.order.permId) if t.order.permId else None,
        raw={"ib_status": st.status},
    )


async def get_open_orders(ib) -> list[OrderUpdate]:
    return [_trade_to_update(t) for t in await ib.reqAllOpenOrdersAsync()]


async def get_order_status(ib, order_id: str) -> OrderStatus:
    for t in await ib.reqAllOpenOrdersAsync():
        if order_id in (str(t.order.orderId), str(t.order.permId)):
            return map_ib_status(
                t.orderStatus.status, t.orderStatus.filled, t.orderStatus.remaining
            )
    raise ValueError(f"Order {order_id} not found among open orders.")


async def get_executions(ib, since: datetime) -> list[OrderUpdate]:
    out = []
    for f in await ib.reqExecutionsAsync():
        if f.time < since:
            continue
        out.append(
            OrderUpdate(
                order_id=str(f.execution.execId),
                status=OrderStatus.FILLED,
                filled_quantity=Decimal(str(f.execution.shares)),
                fill_price=float(f.execution.price),
                timestamp=f.time,
                broker_order_id=None,
                raw={
                    "side": f.execution.side,
                    "commission": getattr(f.commissionReport, "commission", None),
                    "realized_pnl": getattr(f.commissionReport, "realizedPNL", None),
                },
            )
        )
    return out
