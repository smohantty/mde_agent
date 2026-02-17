from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agent.types import LlmRequestMeta


@dataclass
class LlmResult:
    data: dict[str, Any] | str
    meta: LlmRequestMeta


class BaseLlmClient(ABC):
    provider: str

    @abstractmethod
    def complete_structured(
        self, prompt: str, model: str, max_tokens: int, attempt: int
    ) -> LlmResult:
        raise NotImplementedError
