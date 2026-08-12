"""Outline cataloging writes."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ...database.models import CatalogingCandidate, Chapter, OutlineNode
from ..story_granularity import chapter_outline_node, extract_chapter_number, normalize_section_scene_state
from .facts import record_cataloging_fact
from .links import link_outline_characters
from .lookups import find_outline_by_title_or_id, next_outline_sort_order, normalize_lookup
from .merge import merge_text
from .snapshots import outline_snapshot


def apply_outline(
    db: Session,
    candidate: CatalogingCandidate,
    chapter: Chapter,
    payload: dict[str, Any],
    create: bool,
) -> dict[str, Any]:
    title = str(payload.get("title") or payload.get("target_name") or chapter.title).strip()
    if not title:
        raise ValueError("大纲标题为空")
    node_type = str(payload.get("node_type") or "chapter")[:20]
    if node_type == "scene":
        node_type = "section"
    parent = _resolve_requested_parent(
        db,
        chapter.project_id,
        payload.get("parent_id") or payload.get("parent_title"),
    )
    if node_type == "volume":
        parent_id = None
    elif node_type == "chapter":
        volume = parent if parent and parent.node_type == "volume" else _volume_for_chapter(db, chapter)
        parent_id = volume.id
    else:
        chapter_parent = chapter_outline_node(db, chapter.project_id, chapter)
        if not chapter_parent and parent and parent.node_type == "chapter":
            chapter_parent = parent
        if not chapter_parent:
            chapter_parent = _ensure_chapter_container(db, chapter)
        parent_id = chapter_parent.id
    node = _find_outline_for_candidate(
        db,
        chapter,
        payload.get("id") or title,
        node_type,
        exact=create,
    )
    old = outline_snapshot(node) if node else None
    if not node:
        node = OutlineNode(
            project_id=chapter.project_id,
            parent_id=parent_id,
            node_type=node_type,
            title=title[:200],
            summary=str(payload.get("summary") or payload.get("actual_summary") or "")[:8000],
            status=str(payload.get("status") or "completed")[:20],
            source_chapter_id=chapter.id,
            actual_summary=str(payload.get("actual_summary") or payload.get("summary") or "")[:8000],
            planned_summary=str(payload.get("planned_summary") or "")[:8000],
            cataloging_status="cataloged",
            sort_order=next_outline_sort_order(db, chapter.project_id, parent_id),
        )
        db.add(node)
        db.flush()
    else:
        if node.parent_id != parent_id:
            node.parent_id = parent_id
        if payload.get("node_type"):
            node.node_type = node_type
        if payload.get("title"):
            node.title = title[:200]
        if payload.get("summary") or payload.get("actual_summary"):
            node.summary = merge_text(node.summary, payload.get("summary") or payload.get("actual_summary"), chapter, limit=8000)
            node.actual_summary = merge_text(node.actual_summary, payload.get("actual_summary") or payload.get("summary"), chapter, limit=8000)
        if payload.get("planned_summary"):
            node.planned_summary = merge_text(node.planned_summary, payload.get("planned_summary"), chapter, limit=8000)
        if payload.get("status"):
            node.status = str(payload.get("status"))[:20]
        node.source_chapter_id = node.source_chapter_id or chapter.id
        node.cataloging_status = "cataloged"

    if node.node_type == "chapter":
        chapter.outline_node_id = node.id
    elif parent_id and not chapter.outline_node_id:
        chapter.outline_node_id = parent_id
    link_outline_characters(db, chapter.project_id, node, payload.get("related_characters"))
    scene_state = normalize_section_scene_state(payload)
    fact = None
    if scene_state:
        scene_state.setdefault("outline_node_id", node.id)
        scene_state.setdefault("title", node.title)
        scene_state.setdefault("chapter_id", chapter.id)
        scene_state.setdefault("chapter_title", chapter.title)
        fact = record_cataloging_fact(
            db,
            candidate,
            chapter,
            fact_type="section_scene_state",
            payload=scene_state,
            identity_keys=("outline_node_id", "title"),
        )
    return {
        "target_type": "outline_node",
        "target_id": node.id,
        "old_value": old,
        "new_value": {**outline_snapshot(node), "scene_fact_id": fact.id if fact else None},
        "detail": "大纲节点已写入",
    }


def _find_exact_outline(db: Session, project_id: str, value: Any) -> OutlineNode | None:
    text = str(value or "").strip()
    if not text:
        return None
    return (
        db.query(OutlineNode)
        .filter(OutlineNode.project_id == project_id)
        .filter((OutlineNode.id == text) | (OutlineNode.title == text))
        .order_by(OutlineNode.updated_at.desc())
        .first()
    )


def _find_outline_for_candidate(
    db: Session,
    chapter: Chapter,
    value: Any,
    node_type: str,
    *,
    exact: bool,
) -> OutlineNode | None:
    node = (
        _find_exact_outline(db, chapter.project_id, value)
        if exact
        else find_outline_by_title_or_id(db, chapter.project_id, value)
    )
    if node or node_type != "section":
        return node

    # Builds predating the hierarchy fix stored a bare scene title, while the
    # current normalization uses "chapter / scene".  Match only within the
    # same source chapter so re-cataloging repairs the old row instead of
    # creating a duplicate or touching an identically named scene elsewhere.
    title = str(value or "").strip()
    suffix = title.rsplit("/", 1)[-1].strip()
    wanted = normalize_lookup(suffix)
    if not wanted:
        return None
    candidates = (
        db.query(OutlineNode)
        .filter(
            OutlineNode.project_id == chapter.project_id,
            OutlineNode.node_type == "section",
            OutlineNode.source_chapter_id == chapter.id,
        )
        .order_by(OutlineNode.updated_at.desc())
        .all()
    )
    return next(
        (candidate for candidate in candidates if normalize_lookup(candidate.title) == wanted),
        None,
    )


def _resolve_requested_parent(db: Session, project_id: str, value: Any) -> OutlineNode | None:
    """Resolve either a UUID or a provider-supplied title to a real node.

    API models commonly put a chapter title in ``parent_id``.  Persisting that
    title in the UUID column makes the section look like a root node and also
    leaves a broken foreign key.  Never pass an unresolved provider value
    through to storage.
    """

    text = str(value or "").strip()
    return find_outline_by_title_or_id(db, project_id, text) if text else None


def _volume_for_chapter(db: Session, chapter: Chapter) -> OutlineNode:
    volumes = (
        db.query(OutlineNode)
        .filter(OutlineNode.project_id == chapter.project_id, OutlineNode.node_type == "volume")
        .order_by(OutlineNode.sort_order.asc(), OutlineNode.created_at.asc())
        .all()
    )
    chapter_number = extract_chapter_number(chapter.title)
    if volumes:
        if chapter_number is not None:
            ranged: list[tuple[int, OutlineNode]] = []
            for volume in volumes:
                metadata = volume.metadata_json if isinstance(volume.metadata_json, dict) else {}
                try:
                    start = int(metadata.get("start_chapter") or 0)
                    end = int(metadata.get("end_chapter") or 0)
                except (TypeError, ValueError):
                    continue
                if start and (not end or start <= chapter_number <= end):
                    ranged.append((start, volume))
            if ranged:
                return max(ranged, key=lambda item: item[0])[1]
        return volumes[0]

    volume = OutlineNode(
        project_id=chapter.project_id,
        parent_id=None,
        node_type="volume",
        title="第一卷",
        summary="作品建档自动建立的默认分卷；可在大纲中重命名或调整章节范围。",
        status="in_progress",
        source_chapter_id=chapter.id,
        actual_summary="",
        planned_summary="",
        metadata_json={
            "source": "cataloging_default_volume",
            "start_chapter": 1,
        },
        cataloging_status="cataloged",
        sort_order=next_outline_sort_order(db, chapter.project_id, None),
    )
    db.add(volume)
    db.flush()
    return volume


def _ensure_chapter_container(db: Session, chapter: Chapter) -> OutlineNode:
    existing = chapter_outline_node(db, chapter.project_id, chapter)
    if existing:
        return existing
    volume = _volume_for_chapter(db, chapter)
    node = OutlineNode(
        project_id=chapter.project_id,
        parent_id=volume.id,
        node_type="chapter",
        title=chapter.title[:200],
        summary="",
        status="completed",
        source_chapter_id=chapter.id,
        actual_summary="",
        planned_summary="",
        cataloging_status="cataloged",
        sort_order=next_outline_sort_order(db, chapter.project_id, volume.id),
    )
    db.add(node)
    db.flush()
    chapter.outline_node_id = node.id
    return node
