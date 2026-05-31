"""Typed IBKR error domain + classifiers. Pure stdlib — no ib_async, no mcp.

The MCP tool layer lets these propagate; FastMCP serializes str(exc) to the
client, so each error must carry an actionable, human-readable message.
"""


class IBKRError(Exception):
    """Base for typed IBKR errors. `code` is a stable machine-readable tag."""

    code = "IBKR_ERROR"


class BrokerUnavailable(IBKRError):
    code = "BROKER_UNAVAILABLE"


class MarketDataNotEntitled(IBKRError):
    code = "MARKET_DATA_NOT_ENTITLED"


class OrderRejected(IBKRError):
    code = "ORDER_REJECTED"


class ContractNotFound(IBKRError):
    code = "CONTRACT_NOT_FOUND"


def broker_unavailable_from_connect(exc: Exception, host: str, port: int) -> BrokerUnavailable:
    """Map a connectAsync failure to a BrokerUnavailable with an actionable hint."""
    if isinstance(exc, ConnectionRefusedError):
        hint = "nothing is listening — is IB Gateway/TWS running and logged in?"
    elif isinstance(exc, TimeoutError):
        hint = (
            "the socket opened but the IBKR API handshake did not complete — check that "
            "the API is enabled and any 'accept incoming connection' dialog is approved."
        )
    else:
        hint = str(exc) or exc.__class__.__name__
    return BrokerUnavailable(f"IB Gateway not reachable on {host}:{port}: {hint}")


# IBKR error codes we classify. Benign info codes (data-farm OK, etc.) → None.
_MARKET_DATA_NOT_ENTITLED = {354, 10089, 10197}
_BROKER_UNAVAILABLE = {502, 504, 1100, 1300, 2110}
_BENIGN_INFO = {2104, 2106, 2107, 2108, 2158}


def classify_ib_error(code: int, message: str) -> IBKRError | None:
    """Map an IBKR errorEvent (code, message) to a typed error, or None if benign/unknown."""
    if code in _BENIGN_INFO:
        return None
    if code in _MARKET_DATA_NOT_ENTITLED:
        return MarketDataNotEntitled(f"Market data not subscribed (IBKR {code}): {message}")
    if code == 200:
        return ContractNotFound(f"No security definition found (IBKR 200): {message}")
    if code == 201:
        return OrderRejected(f"Order rejected (IBKR 201): {message}")
    if code in _BROKER_UNAVAILABLE:
        return BrokerUnavailable(f"Broker connectivity issue (IBKR {code}): {message}")
    return None
