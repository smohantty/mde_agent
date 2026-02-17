from __future__ import annotations

import signal
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from types import FrameType


@dataclass
class SignalState:
    stop_requested: bool = False
    signal_name: str | None = None


def _resolve_signal_name(signum: int) -> str:
    for name in ("SIGINT", "SIGTERM"):
        if getattr(signal, name, None) == signum:
            return name
    return str(signum)


@contextmanager
def install_signal_handlers() -> Iterator[SignalState]:
    state = SignalState()

    def _handler(signum: int, _: FrameType | None) -> None:
        state.stop_requested = True
        state.signal_name = _resolve_signal_name(signum)

    original_int = signal.getsignal(signal.SIGINT)
    original_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    try:
        yield state
    finally:
        signal.signal(signal.SIGINT, original_int)
        signal.signal(signal.SIGTERM, original_term)
