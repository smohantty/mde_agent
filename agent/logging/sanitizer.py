from __future__ import annotations

import re

# Keep common whitespace control characters, remove the rest.
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str) -> str:
    return _CONTROL_PATTERN.sub("", text)
