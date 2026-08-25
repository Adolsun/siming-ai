"""Repair cataloging-generated outline hierarchy.

Revision ID: 300a14_cataloging_outline_hierarchy
Revises: 300a13_narrative_resolution_evidence
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "300a14_cataloging_outline_hierarchy"
down_revision = "300a13_narrative_resolution_evidence"
branch_labels = None
depends_on = None


def _json_storage_value(column: sa.Column, value: dict) -> dict | str:
    """Encode JSON explicitly for legacy SQLite columns declared as TEXT."""

    if isinstance(column.type, sa.JSON):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "outline_nodes" not in inspector.get_table_names():
        return
    required = {
        "id",
        "project_id",
        "parent_id",
        "node_type",
        "title",
        "summary",
        "status",
        "source_chapter_id",
        "actual_summary",
        "planned_summary",
        "metadata_json",
        "cataloging_status",
        "sort_order",
        "created_at",
        "updated_at",
    }
    columns = {column["name"] for column in inspector.get_columns("outline_nodes")}
    if not required <= columns:
        return

    metadata = sa.MetaData()
    outline = sa.Table("outline_nodes", metadata, autoload_with=bind)
    nodes = [dict(row) for row in bind.execute(sa.select(outline)).mappings()]
    by_id = {str(node["id"]): node for node in nodes}
    chapters = [node for node in nodes if node.get("node_type") == "chapter"]

    # Affected builds stored a chapter title in section.parent_id.  Repair only
    # an unambiguous same-project chapter match, preferring the same source
    # chapter when available.
    for section in (node for node in nodes if node.get("node_type") == "section"):
        parent = by_id.get(str(section.get("parent_id") or ""))
        if parent and parent.get("node_type") == "chapter":
            continue
        candidates = [
            chapter
            for chapter in chapters
            if chapter.get("project_id") == section.get("project_id")
            and (
                chapter.get("title") == section.get("parent_id")
                or (
                    section.get("source_chapter_id")
                    and chapter.get("source_chapter_id") == section.get("source_chapter_id")
                )
            )
        ]
        same_source = [
            chapter
            for chapter in candidates
            if section.get("source_chapter_id")
            and chapter.get("source_chapter_id") == section.get("source_chapter_id")
        ]
        selected = (same_source or candidates)[0] if len(same_source or candidates) == 1 else None
        if selected:
            bind.execute(
                outline.update()
                .where(outline.c.id == section["id"])
                .values(parent_id=selected["id"], updated_at=datetime.utcnow())
            )
            section["parent_id"] = selected["id"]

    # Only cataloging-owned root chapters are normalized.  User-authored root
    # nodes are deliberately left untouched.
    root_chapters: dict[str, list[dict]] = {}
    for chapter in chapters:
        if chapter.get("parent_id") is not None:
            continue
        if chapter.get("cataloging_status") != "cataloged" and not chapter.get("source_chapter_id"):
            continue
        root_chapters.setdefault(str(chapter["project_id"]), []).append(chapter)

    volumes_by_project: dict[str, list[dict]] = {}
    for node in nodes:
        if node.get("node_type") == "volume":
            volumes_by_project.setdefault(str(node["project_id"]), []).append(node)

    for project_id, project_chapters in root_chapters.items():
        volumes = volumes_by_project.get(project_id) or []
        if volumes:
            # Without a persisted chapter range there is no safe way for a
            # migration to choose among several author-defined volumes.
            if len(volumes) != 1:
                continue
            volume_id = volumes[0]["id"]
        else:
            now = datetime.utcnow()
            volume_id = str(uuid4())
            bind.execute(outline.insert().values(
                id=volume_id,
                project_id=project_id,
                parent_id=None,
                node_type="volume",
                title="第一卷",
                summary="作品建档自动建立的默认分卷；可在大纲中重命名或调整章节范围。",
                status="in_progress",
                source_chapter_id=project_chapters[0].get("source_chapter_id"),
                actual_summary="",
                planned_summary="",
                metadata_json=_json_storage_value(
                    outline.c.metadata_json,
                    {"source": "cataloging_default_volume", "start_chapter": 1},
                ),
                cataloging_status="cataloged",
                sort_order=0,
                created_at=now,
                updated_at=now,
            ))
        for chapter in project_chapters:
            bind.execute(
                outline.update()
                .where(outline.c.id == chapter["id"])
                .values(parent_id=volume_id, updated_at=datetime.utcnow())
            )


def downgrade() -> None:
    # The repaired references are valid user data.  Re-introducing broken
    # title-valued foreign keys on downgrade would be destructive.
    pass
