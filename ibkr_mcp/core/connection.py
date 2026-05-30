"""IBKRConnection — owns the single ib_async.IB() instance and its lifecycle.

Imports ib_async; MUST NOT import mcp/FastMCP (extractable-core invariant).
Lazy-connect-at-tool-entry pattern: the server runs even if the Gateway is
down; health() reports the state and tools call ensure_connected() first.
"""

from collections.abc import Callable
from datetime import datetime, timezone

import ib_async

from ibkr_mcp.core.models import BrokerHealth

# IBKR socket convention: paper = 4002 (Gateway) / 7497 (TWS),
# live = 4001 (Gateway) / 7496 (TWS).
_PAPER_PORTS = frozenset({4002, 7497})


class IBKRConnection:
    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        *,
        readonly: bool = True,
        ib_factory: Callable[[], "ib_async.IB"] = ib_async.IB,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.readonly = readonly
        self._ib = ib_factory()

    # Internal accessor for core READS (e.g. account/positions). Not a write path:
    # order placement will go through guarded methods, not this raw IB handle.
    @property
    def ib(self) -> "ib_async.IB":
        return self._ib

    @property
    def is_paper(self) -> bool:
        return self.port in _PAPER_PORTS

    async def ensure_connected(self) -> None:
        if self._ib.isConnected():
            return
        await self._ib.connectAsync(
            self.host, self.port, clientId=self.client_id, readonly=self.readonly
        )

    async def health(self) -> BrokerHealth:
        connected = self._ib.isConnected()
        # M1: no Gateway heartbeat subscription yet. While connected we stamp
        # last_heartbeat_at with the poll time (not a true broker heartbeat);
        # real heartbeat tracking arrives with the Watchdog in a later milestone.
        # Field name kept aligned with the Aegis BrokerHealth shape on purpose.
        return BrokerHealth(
            connected=connected,
            last_heartbeat_at=datetime.now(timezone.utc) if connected else None,
        )

    def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()
