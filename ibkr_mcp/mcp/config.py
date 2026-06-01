"""MCP-layer configuration. No ib_async import here."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

_TRUTHY = {"1", "true", "yes", "on"}
_LIVE_PORTS = {4001, 7496}


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 4002  # paper Gateway by default
    client_id: int = 1
    read_only: bool = True
    allow_live: bool = False
    max_order_qty: Decimal | None = None
    max_order_notional_usd: float | None = None
    ticker_allowlist: frozenset[str] | None = None
    state_dir: Path = field(default_factory=lambda: Path.home() / ".ibkr-mcp")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        qty = env.get("IBKR_MAX_ORDER_QTY")
        notional = env.get("IBKR_MAX_ORDER_NOTIONAL_USD")
        allowlist = env.get("IBKR_TICKER_ALLOWLIST")
        state_dir = env.get("IBKR_STATE_DIR")
        return cls(
            host=env.get("IBKR_HOST", "127.0.0.1"),
            port=int(env.get("IBKR_PORT", "4002")),
            client_id=int(env.get("IBKR_CLIENT_ID", "1")),
            read_only=env.get("IBKR_READ_ONLY", "true").strip().lower() in _TRUTHY,
            allow_live=env.get("IBKR_ALLOW_LIVE", "false").strip().lower() in _TRUTHY,
            max_order_qty=Decimal(qty) if qty else None,
            max_order_notional_usd=float(notional) if notional else None,
            ticker_allowlist=(
                frozenset(t.strip().upper() for t in allowlist.split(",") if t.strip())
                if allowlist
                else None
            ),
            state_dir=Path(state_dir) if state_dir else (Path.home() / ".ibkr-mcp"),
        )

    def validate(self) -> None:
        """Refuse a writable server pointed at a live port without explicit opt-in."""
        if not self.read_only and not self.allow_live and self.port in _LIVE_PORTS:
            raise ValueError(
                f"Refusing to start: writable server on live port {self.port} without "
                "IBKR_ALLOW_LIVE=true. Set IBKR_READ_ONLY=true, use a paper port (4002), "
                "or set IBKR_ALLOW_LIVE=true to trade live deliberately."
            )
