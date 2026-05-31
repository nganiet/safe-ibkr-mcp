import pytest

from ibkr_mcp.core.errors import (
    BrokerUnavailable,
    ContractNotFound,
    IBKRError,
    MarketDataNotEntitled,
    OrderRejected,
    broker_unavailable_from_connect,
    classify_ib_error,
)


def test_error_codes():
    assert IBKRError.code == "IBKR_ERROR"
    assert BrokerUnavailable.code == "BROKER_UNAVAILABLE"
    assert MarketDataNotEntitled.code == "MARKET_DATA_NOT_ENTITLED"
    assert OrderRejected.code == "ORDER_REJECTED"
    assert ContractNotFound.code == "CONTRACT_NOT_FOUND"
    assert issubclass(BrokerUnavailable, IBKRError)


def test_str_is_the_message():
    e = BrokerUnavailable("gateway down")
    assert str(e) == "gateway down"
    assert e.code == "BROKER_UNAVAILABLE"


def test_broker_unavailable_from_connect_refused():
    e = broker_unavailable_from_connect(ConnectionRefusedError(61, "refused"), "127.0.0.1", 4001)
    assert isinstance(e, BrokerUnavailable)
    assert "127.0.0.1:4001" in str(e)
    assert "running" in str(e).lower()  # actionable hint


def test_broker_unavailable_from_connect_timeout():
    e = broker_unavailable_from_connect(TimeoutError(), "127.0.0.1", 4001)
    assert isinstance(e, BrokerUnavailable)
    assert "handshake" in str(e).lower()  # the modal/api-not-enabled case


@pytest.mark.parametrize(
    "code,expected",
    [
        (354, MarketDataNotEntitled),
        (10089, MarketDataNotEntitled),
        (10197, MarketDataNotEntitled),
        (200, ContractNotFound),
        (201, OrderRejected),
        (1100, BrokerUnavailable),
        (502, BrokerUnavailable),
    ],
)
def test_classify_ib_error_known_codes(code, expected):
    err = classify_ib_error(code, "msg")
    assert isinstance(err, expected)
    assert "msg" in str(err) or str(code) in str(err)


@pytest.mark.parametrize("code", [2104, 2106, 2158])
def test_classify_ib_error_benign_info_codes_return_none(code):
    assert classify_ib_error(code, "data farm OK") is None


def test_classify_ib_error_unknown_returns_none():
    assert classify_ib_error(99999, "mystery") is None
