"""Rebuild the chapter write gate from durable v1 author-data evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


class ProjectPackageChapterCatalogingState:
    """v1 omits job state; an old summary alone cannot release a newer chapter."""

    def __init__(self, snapshots: list[dict[str, Any]], summaries: list[dict[str, Any]]):
        self.snapshots: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.summaries: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in snapshots:
            self.snapshots[str(row.get("chapter_id") or "")].append(row)
        for row in summaries:
            self.summaries[str(row.get("chapter_id") or "")].append(row)

    def required(self, chapter: dict[str, Any]) -> bool:
        content = str(chapter.get("content") or "")
        if not content.strip():
            return False
        chapter_id = str(chapter.get("id") or "")
        version = chapter.get("current_version")
        if not chapter_id or type(version) is not int or version < 1:
            return True
        summary_times = [
            timestamp
            for row in self.summaries.get(chapter_id, [])
            if str(row.get("summary_text") or "").strip()
            if (timestamp := _timestamp(row.get("updated_at") or row.get("created_at"))) is not None
        ]
        for snapshot in self.snapshots.get(chapter_id, []):
            if snapshot.get("version_number") != version or snapshot.get("content") != content:
                continue
            saved_at = _timestamp(snapshot.get("created_at"))
            if saved_at is not None and any(timestamp >= saved_at for timestamp in summary_times):
                return False
        return True
