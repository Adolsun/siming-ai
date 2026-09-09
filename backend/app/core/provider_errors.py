"""Deterministic parsing of upstream HTTP/protocol errors, never author intent."""

from __future__ import annotations

import re

from app.core.exceptions import AppException

_HTTP_STATUS = re.compile(
    r"\b(?:http(?:/\d(?:\.\d)?)?|status(?:[_ ]code)?|error\s+code)\s*[:=]?\s*([45]\d{2})\b",
    re.IGNORECASE,
)
_REJECTED_FIELD = re.compile(
    r"not\s+support|unsupported|invalid|missing|required|must\b.*(?:pass|provid|includ)",
    re.IGNORECASE,
)
_OTHER_FAILURE = re.compile(
    r"\b(?:authentication|unauthori[sz]ed|forbidden|quota|rate[ _-]*limit|"
    r"timeout|timed out|connection|network)\b",
    re.IGNORECASE,
)


def provider_http_status(error: BaseException | str) -> int | None:
    """Prefer SDK status metadata, including the original wrapped exception."""
    current = error
    seen: set[int] = set()
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        # AppException.status_code is Siming's public HTTP projection (LLMError
        # is always 502), not the status returned by the upstream provider.
        status = (
            None if isinstance(current, AppException) else getattr(current, "status_code", None)
        )
        if not isinstance(status, int):
            status = getattr(getattr(current, "response", None), "status_code", None)
        if isinstance(status, int) and 400 <= status < 600:
            return status
        current = current.__cause__ or current.__context__
    match = _HTTP_STATUS.search(str(error))
    return int(match.group(1)) if match else None


def provider_field_rejected(error: BaseException | str, *fields: str) -> bool:
    text = str(error).lower()
    if not any(field in text for field in fields):
        return False
    status = provider_http_status(error)
    if status is not None:
        return status in {400, 422}
    if _OTHER_FAILURE.search(text):
        return False
    return bool(_REJECTED_FIELD.search(text))


def provider_protocol_rejected(error: BaseException | str) -> bool:
    return provider_field_rejected(error, "tool_choice", "tool choice", "reasoning_content")
