from __future__ import annotations

import random


def compute_backoff_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    exponential = base_delay * (2 ** max(attempt - 1, 0))
    jitter = random.uniform(0.0, base_delay)
    return min(exponential + jitter, max_delay)
