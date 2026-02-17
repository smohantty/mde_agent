from __future__ import annotations

from agent.logging.redaction import redact_secrets


def scrub(text: str) -> str:
    return redact_secrets(text)
