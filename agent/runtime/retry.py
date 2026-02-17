from __future__ import annotations

import random

# HTTP status codes that are transient and safe to retry.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


def compute_backoff_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    exponential = base_delay * (2 ** max(attempt - 1, 0))
    jitter = random.uniform(0.0, base_delay)
    return min(exponential + jitter, max_delay)


def is_retryable_error(exc: Exception) -> bool:
    """Determine whether a provider API error is transient and worth retrying.

    Non-retryable errors (400 billing/validation, 401 auth, 403 permission,
    404 not found) fail fast to avoid wasting time on errors that won't resolve.
    """
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code in _RETRYABLE_STATUS_CODES

    # Network/connection errors without a status code are transient.
    exc_name = type(exc).__name__.lower()
    return any(term in exc_name for term in ("timeout", "connection", "network"))
