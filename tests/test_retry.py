from __future__ import annotations

from agent.runtime.retry import compute_backoff_delay, is_retryable_error


class FakeApiStatusError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code


def test_retryable_on_rate_limit() -> None:
    exc = FakeApiStatusError(429, "rate limited")
    assert is_retryable_error(exc) is True


def test_retryable_on_server_error() -> None:
    for code in (500, 502, 503, 529):
        exc = FakeApiStatusError(code, "server error")
        assert is_retryable_error(exc) is True, f"Expected {code} to be retryable"


def test_not_retryable_on_billing_error() -> None:
    exc = FakeApiStatusError(400, "credit balance too low")
    assert is_retryable_error(exc) is False


def test_not_retryable_on_auth_error() -> None:
    exc = FakeApiStatusError(401, "invalid api key")
    assert is_retryable_error(exc) is False


def test_not_retryable_on_permission_error() -> None:
    exc = FakeApiStatusError(403, "forbidden")
    assert is_retryable_error(exc) is False


def test_not_retryable_on_not_found() -> None:
    exc = FakeApiStatusError(404, "model not found")
    assert is_retryable_error(exc) is False


def test_retryable_on_timeout_exception() -> None:
    exc = TimeoutError("connection timed out")
    assert is_retryable_error(exc) is True


def test_retryable_on_connection_error() -> None:
    exc = ConnectionError("network unreachable")
    assert is_retryable_error(exc) is True


def test_not_retryable_on_generic_exception() -> None:
    exc = RuntimeError("something unexpected")
    assert is_retryable_error(exc) is False


def test_backoff_delay_increases() -> None:
    d1 = compute_backoff_delay(1, base_delay=1.0, max_delay=30.0)
    d2 = compute_backoff_delay(2, base_delay=1.0, max_delay=30.0)
    d3 = compute_backoff_delay(3, base_delay=1.0, max_delay=30.0)
    assert d1 < d3
    assert d2 < d3


def test_backoff_delay_respects_max() -> None:
    d = compute_backoff_delay(10, base_delay=1.0, max_delay=8.0)
    assert d <= 8.0
