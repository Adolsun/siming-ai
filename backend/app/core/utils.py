"""Shared pure utility functions."""
from __future__ import annotations

import re
from datetime import UTC, datetime


def utc_isoformat(value: datetime | None) -> str | None:
    """Serialize a database UTC timestamp with an explicit UTC offset.

    SQLite returns timezone-naive ``datetime`` values even when the stored
    convention is UTC.  Sending their bare ``isoformat()`` value makes a web
    client interpret UTC as local time.  Preserve aware inputs and make the
    database convention explicit for naive values.
    """

    if value is None:
        return None
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return aware.astimezone(UTC).isoformat()


def count_words(text: str) -> int:
    """Count characters excluding spaces and newlines, matching mainstream novel platforms."""
    return len(re.sub(r"[\s]", "", text))
