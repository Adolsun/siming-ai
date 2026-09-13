"""Worldbuilding cataloging writes."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ...database.models import (
    CatalogingCandidate,
    Chapter,
    WorldbuildingEntry,
    WorldbuildingTimeline,
    WorldbuildingVersion,
)
from ...database.query_filters import is_current_worldbuilding_status
from .candidate_io import float_or_none
from .constants import WORLD_DIMENSIONS
from .links import link_chapter_worldbuilding
from .lookups import find_worldbuilding_by_title_or_id, next_worldbuilding_sort_order
from .merge import merge_text
from .snapshots import chapter_change_title, worldbuilding_snapshot




def apply_worldbuilding(
    db: Session,
    candidate: CatalogingCandidate,
    chapter: Chapter,
    payload: dict[str, Any],
    create: bool,
) -> dict:
    title = str(payload.get("title") or "").strip()
    if not title or _is_placeholder_worldbuilding_title(title):
        raise ValueError("世界观标题为空")
    content = str(payload.get("content") or payload.get("description") or payload.get("evidence") or candidate.evidence or "").strip()
    if not content:
        raise ValueError("世界观内容为空")
    dimension = _normalize_dimension(payload.get("dimension"), payload)
    entry_id = str(payload.get("id") or "").strip()
    if not create and not entry_id:
        raise ValueError("世界观更新必须使用上下文中已有条目的精确 ID")
    if create:
        client_id = payload.get("client_id")
        if entry_id or not client_id or db.get(WorldbuildingEntry, client_id) is not None:
            raise ValueError("新设定必须使用未占用的 client_id；已有设定使用 worldbuilding_update")
        collision = db.query(WorldbuildingEntry).filter_by(project_id=chapter.project_id, title=title).first()
        if collision:
            raise ValueError(f"设定标题已存在，不能通过 create 覆盖或重新激活；请读取档案 ID={collision.id}")
        entry = None
    else:
        entry = _find_current_worldbuilding_target(db, chapter.project_id, entry_id, explicit_id=entry_id)
        if not entry:
            raise ValueError("世界观更新目标 ID 不存在、已停用或不属于当前作品")
    old = worldbuilding_snapshot(entry) if entry else None
    if not entry:
        if not dimension:
            raise ValueError("worldbuilding_create.dimension 必填")
        entry = WorldbuildingEntry(
            project_id=chapter.project_id,
            dimension=dimension,
            title=title[:200],
            content=content[:12000],
            sort_order=next_worldbuilding_sort_order(db, chapter.project_id, dimension),
            first_seen_chapter_id=chapter.id,
            last_updated_chapter_id=chapter.id,
            status="active",
            confidence=float_or_none(candidate.confidence),
        )
        if payload.get("client_id"):
            entry.id = payload["client_id"]
        db.add(entry)
        db.flush()
    else:
        entry.status = "active"
        entry.dimension = dimension or entry.dimension
        if content:
            previous = payload.get("_cataloging_previous_payload")
            previous = previous if isinstance(previous, dict) else {}
            previous_content = str(
                previous.get("content")
                or previous.get("description")
                or previous.get("evidence")
                or ""
            ).strip()
            current_content = str(entry.content or "")
            entry.content = (
                current_content.replace(previous_content, content, 1)[:12000]
                if previous_content and previous_content in current_content
                else merge_text(current_content, content, chapter, limit=12000)
            )
        # A cataloging update is bound by the exact existing ID.  The model may
        # mention that entity with a shorter alias in chapter prose, but that
        # alias must not silently rename the author's canonical world card.
        # Authors can still rename a card through the worldbuilding edit API.
        if create:
            entry.title = title[:200]
        if _chapter_can_advance_world_state(db, entry, chapter):
            entry.last_updated_chapter_id = chapter.id
        entry.confidence = float_or_none(candidate.confidence) or entry.confidence
    if old is None or worldbuilding_snapshot(entry) != old:
        ensure_worldbuilding_version(db, entry, chapter, payload)
    link_chapter_worldbuilding(
        db,
        chapter,
        entry,
        str(payload.get("description") or payload.get("evidence") or ""),
    )
    return {
        "target_type": "worldbuilding",
        "target_id": entry.id,
        "old_value": old,
        "new_value": worldbuilding_snapshot(entry),
        "detail": f"世界观已写入: {entry.title}",
    }


def apply_worldbuilding_timeline(db: Session, candidate: CatalogingCandidate, chapter: Chapter, payload: dict[str, Any]) -> dict:
    entry_id = str(payload.get("id") or "").strip()
    entry = _find_current_worldbuilding_target(
        db,
        chapter.project_id,
        entry_id or payload.get("title"),
        explicit_id=entry_id,
    )
    if entry_id and not entry:
        raise ValueError("世界观时间线目标 ID 不存在或不属于当前作品")
    if not entry:
        raise ValueError("世界观时间线需要计划内已创建的真实设定 ID")
    description = str(payload.get("event_description") or payload.get("description") or "")[:4000]
    if not description:
        raise ValueError("世界观时间线事件为空")
    event_type = str(payload.get("event_type") or "fact_change")[:50]
    sort_order = int(payload.get("sort_order") or candidate.sort_order or 0)
    preferred_id = str(payload.get("_cataloging_target_id") or "").strip()
    event = (
        db.query(WorldbuildingTimeline)
        .filter(
            WorldbuildingTimeline.id == preferred_id,
            WorldbuildingTimeline.chapter_id == chapter.id,
            WorldbuildingTimeline.entry_id == entry.id,
        )
        .first()
        if preferred_id
        else None
    )
    if not event:
        event = (
            db.query(WorldbuildingTimeline)
            .filter(
                WorldbuildingTimeline.entry_id == entry.id,
                WorldbuildingTimeline.chapter_id == chapter.id,
                WorldbuildingTimeline.event_type == event_type,
                WorldbuildingTimeline.sort_order == sort_order,
            )
            .order_by(WorldbuildingTimeline.created_at.asc())
            .first()
        )
    old = None
    if event:
        old = {
            "event_description": event.event_description,
            "event_type": event.event_type,
            "evidence": event.evidence,
            "sort_order": event.sort_order,
        }
        event.event_description = description
        event.event_type = event_type
        event.evidence = str(payload.get("evidence") or candidate.evidence or "")[:2000]
        event.sort_order = sort_order
    else:
        event = WorldbuildingTimeline(
            entry_id=entry.id,
            chapter_id=chapter.id,
            event_description=description,
            event_type=event_type,
            evidence=str(payload.get("evidence") or candidate.evidence or "")[:2000],
            sort_order=sort_order,
        )
        db.add(event)
    link_chapter_worldbuilding(db, chapter, entry, event.event_description)
    db.flush()
    return {
        "target_type": "worldbuilding_timeline",
        "target_id": event.id,
        "old_value": old,
        "new_value": payload,
        "detail": f"世界观时间线已写入: {entry.title}",
    }


def _is_placeholder_worldbuilding_title(title: str | None) -> bool:
    text = str(title or "").strip()
    return not text


def _find_current_worldbuilding_target(
    db: Session,
    project_id: str,
    value: Any,
    *,
    explicit_id: str = "",
) -> WorldbuildingEntry | None:
    """Resolve only the current author-approved projection.

    Re-cataloging reconciliation handles an intentionally retired target before
    reaching this helper. Ordinary candidates must never revive an archived,
    superseded, or draft row merely because they retained its old ID.
    """

    entry = find_worldbuilding_by_title_or_id(db, project_id, value)
    if entry is not None or not explicit_id:
        return entry
    historical = db.get(WorldbuildingEntry, explicit_id)
    if (
        historical is not None
        and historical.project_id == project_id
        and not is_current_worldbuilding_status(historical.status)
    ):
        raise ValueError(
            "世界观目标 ID 已停用，不能重新激活；请改用当前 active 条目的精确 ID"
        )
    return None


def _chapter_can_advance_world_state(
    db: Session,
    entry: WorldbuildingEntry,
    chapter: Chapter,
) -> bool:
    if not entry.last_updated_chapter_id or entry.last_updated_chapter_id == chapter.id:
        return True
    latest = db.query(Chapter).filter(Chapter.id == entry.last_updated_chapter_id).first()
    if not latest:
        return True
    return int(chapter.sort_order or 0) >= int(latest.sort_order or 0)


def ensure_worldbuilding_version(
    db: Session,
    entry: WorldbuildingEntry,
    chapter: Chapter,
    payload: dict[str, Any],
) -> None:
    current = db.query(func.max(WorldbuildingVersion.version_number)).filter(
        WorldbuildingVersion.entry_id == entry.id
    ).scalar() or 0
    db.add(WorldbuildingVersion(
        entry_id=entry.id,
        version_number=int(current) + 1,
        snapshot_data=json.dumps(worldbuilding_snapshot(entry), ensure_ascii=False),
        change_summary=chapter_change_title(
            chapter,
            payload.get("change_summary") or payload.get("event_description") or "设定更新",
        ),
        source_chapter_id=chapter.id,
    ))






def _normalize_dimension(value: Any, payload: dict[str, Any] | None = None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in WORLD_DIMENSIONS:
        raise ValueError("dimension 必须使用工具契约中的枚举值")
    return value
