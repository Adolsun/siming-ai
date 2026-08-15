"""UTC serialization contract shared by browser-facing APIs."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.core.utils import utc_isoformat


def test_naive_database_datetime_is_serialized_as_explicit_utc() -> None:
    assert utc_isoformat(datetime(2026, 8, 14, 15, 30, 0)) == "2026-08-14T15:30:00+00:00"


def test_aware_datetime_is_converted_to_utc_without_changing_the_instant() -> None:
    china_time = datetime(2026, 8, 14, 23, 30, 0, tzinfo=timezone(timedelta(hours=8)))
    assert utc_isoformat(china_time) == datetime(2026, 8, 14, 15, 30, 0, tzinfo=UTC).isoformat()


def test_none_datetime_remains_none() -> None:
    assert utc_isoformat(None) is None
