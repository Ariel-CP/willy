"""
security_utils.py - Helpers to reduce accidental secret exposure in logs.
"""

from __future__ import annotations

import re


_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI-like keys (sk-..., sk-proj-...)
    (re.compile(r"\bsk(?:-proj)?-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    # Generic credential assignments and inline values.
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|auth)\b\s*([:=])\s*([^\s,;\]\)}]+)"
        ),
        r"\1\2[REDACTED]",
    ),
    # Authorization Bearer tokens.
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s]+)"), r"\1[REDACTED_TOKEN]"),
]


def redact_sensitive_text(text: str, max_chars: int | None = None) -> str:
    """Return *text* with common secrets masked and optionally truncated."""
    if not isinstance(text, str):
        text = str(text)

    sanitized = text
    for pattern, replacement in _REPLACEMENTS:
        sanitized = pattern.sub(replacement, sanitized)

    if isinstance(max_chars, int) and max_chars > 0 and len(sanitized) > max_chars:
        sanitized = sanitized[:max_chars] + "\n\n[...truncated...]"
    return sanitized