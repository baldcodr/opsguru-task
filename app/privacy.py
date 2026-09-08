from __future__ import annotations

import re
from typing import Any

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def redact_email_addresses(value: str) -> str:
    return EMAIL_PATTERN.sub("[redacted-email]", value)


def sanitize_public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitize_public_value(item)
            for key, item in value.items()
            if "email" not in str(key).casefold()
        }
    if isinstance(value, list | tuple):
        return [sanitize_public_value(item) for item in value]
    if isinstance(value, str):
        return redact_email_addresses(value)
    return value