from __future__ import annotations

import re
from typing import Any


_SENSITIVE_NAME = (
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|"
    r"client[_-]?secret|password|secret|token|cookie|code|key)"
)
_SENSITIVE_DICT_NAME = (
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|"
    r"authorization[_-]?code|oauth[_-]?code|client[_-]?secret|password|"
    r"secret|token|cookie)"
)

_QUERY_SECRET_RE = re.compile(
    rf"([?&]{_SENSITIVE_NAME}=)[^&#\s]+",
    re.IGNORECASE,
)
_ASSIGNMENT_SECRET_RE = re.compile(
    rf"((?:[\"']?{_SENSITIVE_NAME}[\"']?)\s*[:=]\s*[\"']?)[^\"'\s,;&]+",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(
    r"(\bBearer\s+)[A-Za-z0-9._~+/=-]+",
    re.IGNORECASE,
)
_KNOWN_TOKEN_RE = re.compile(
    r"\b(?:github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+|"
    r"sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,})\b"
)


def redact_sensitive_text(value: object) -> str:
    """Remove common credentials from errors before logging or persistence."""
    text = str(value or "")
    text = _QUERY_SECRET_RE.sub(r"\1[REDACTED]", text)
    text = _BEARER_RE.sub(r"\1[REDACTED]", text)
    text = _ASSIGNMENT_SECRET_RE.sub(r"\1[REDACTED]", text)
    return _KNOWN_TOKEN_RE.sub("[REDACTED]", text)


def redact_sensitive(value: Any) -> Any:
    """Recursively redact diagnostic payloads without changing their shape."""
    if isinstance(value, dict):
        output: dict[Any, Any] = {}
        for key, item in value.items():
            if re.fullmatch(_SENSITIVE_DICT_NAME, str(key), re.IGNORECASE):
                output[key] = "[REDACTED]" if item else item
            else:
                output[key] = redact_sensitive(item)
        return output
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value
