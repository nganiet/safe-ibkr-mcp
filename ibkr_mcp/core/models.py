"""Domain dataclasses — copies of the Aegis BrokerAdapter v2 shapes.

Kept aligned with Aegis backend/app/brokers/base.py so a future `ibkr-core`
package can back an IBKRBrokerAdapter without translation.
This module imports neither ib_async nor mcp (extractable-core invariant).
"""

from dataclasses import dataclass
from datetime import datetime


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
