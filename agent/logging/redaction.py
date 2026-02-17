from __future__ import annotations

import re

_SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key\s*[=:]\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(token\s*[=:]\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(authorization\s*:\s*bearer\s+)([^\s]+)", re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(r"\1***REDACTED***", redacted)
    return redacted


def summarize_text(text: str, max_chars: int = 400) -> str:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[:max_chars]}..."
