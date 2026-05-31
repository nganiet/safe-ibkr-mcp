"""Server-enforced order guardrails — paper/live gate, allowlist, size & notional caps.

Pure policy: no ib_async, no mcp. check_order() raises on the first violation and is
safe to call repeatedly (preview AND confirm) with identical results.
"""

from dataclasses import dataclass
from decimal import Decimal


class GuardrailViolation(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GuardrailPolicy:
    max_order_qty: Decimal | None = None
    max_order_notional_usd: float | None = None
    ticker_allowlist: frozenset[str] | None = None  # None = unrestricted
    allow_live: bool = False

    def check_order(
        self,
        *,
        ticker: str,
        qty: Decimal,
        est_price: float | None,
        is_paper: bool,
    ) -> None:
        if not is_paper and not self.allow_live:
            raise GuardrailViolation(
                "LIVE_NOT_ALLOWED",
                "Live trading is disabled (set allow_live + connect to a live port).",
            )
        if self.ticker_allowlist is not None and ticker not in self.ticker_allowlist:
            raise GuardrailViolation(
                "TICKER_NOT_ALLOWED", f"{ticker} is not in the configured allowlist."
            )
        if self.max_order_qty is not None and qty > self.max_order_qty:
            raise GuardrailViolation(
                "MAX_QTY_EXCEEDED",
                f"Order qty {qty} exceeds cap {self.max_order_qty}.",
            )
        if (
            self.max_order_notional_usd is not None
            and est_price is not None
            and float(qty) * est_price > self.max_order_notional_usd
        ):
            raise GuardrailViolation(
                "MAX_NOTIONAL_EXCEEDED",
                f"Order notional {float(qty) * est_price:.2f} USD exceeds cap "
                f"{self.max_order_notional_usd:.2f}.",
            )
