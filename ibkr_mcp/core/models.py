"""Domain dataclasses — copies of the Aegis BrokerAdapter v2 shapes.

Kept aligned with Aegis backend/app/brokers/base.py so a future `ibkr-core`
package can back an IBKRBrokerAdapter without translation.
This module imports neither ib_async nor mcp (extractable-core invariant).
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"
    CRYPTO = "CRYPTO"
    FUTURE = "FUTURE"
    FX = "FX"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class Symbol:
    code: str
    asset_class: AssetClass
    exchange: str | None = None

    @classmethod
    def equity(cls, ticker: str) -> "Symbol":
        return cls(code=ticker.upper(), asset_class=AssetClass.EQUITY)


@dataclass
class PositionInfo:
    ticker: str
    shares: Decimal
    avg_cost: float
    current_price: float
    unrealized_pnl: float
    market_value: float


@dataclass
class OrderUpdate:
    order_id: str
    status: OrderStatus
    filled_quantity: Decimal
    fill_price: float | None
    timestamp: datetime
    broker_order_id: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class BrokerHealth:
    connected: bool
    last_heartbeat_at: datetime | None = None
    latency_ms: float | None = None


@dataclass
class AccountInfo:
    total_value: float
    cash: float
    buying_power: float
    positions_value: float
    unrealized_pnl: float


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


@dataclass
class OrderRequest:
    symbol: Symbol
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "DAY"

    @property
    def ticker(self) -> str:
        return self.symbol.code


@dataclass
class OrderConfirmation:
    order_id: str
    status: OrderStatus
    fill_price: float | None = None
    filled_quantity: Decimal = field(default_factory=lambda: Decimal(0))
    timestamp: datetime | None = None
    broker_order_id: str | None = None
    reject_reason: str | None = None
