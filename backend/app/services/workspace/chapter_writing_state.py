"""Current persisted writing gates exposed as data to every model transport."""
from __future__ import annotations

from typing import Any

from app.services.cataloging.launcher import (
    find_blocking_chapter_cataloging_job,
    find_cataloging_required_chapter,
)
from app.services.workspace.generated_drafts import find_pending_chapter_draft


def load_chapter_writing_state(db: Any, project_id: str) -> dict[str, Any]:
    """Use the same checks as writing tools, without choosing a writing target.

    Old assistant replies and draft tool receipts describe the state at their
    creation time. Author saves and background cataloging can change those
    facts between turns, including while a model step is running.
    """
    draft = find_pending_chapter_draft(db, project_id)
    job = find_blocking_chapter_cataloging_job(db, project_id)
    chapter = find_cataloging_required_chapter(db, project_id)
    return {
        "pending_draft": (
            {
                "id": str(draft.id),
                "title": str(draft.title or ""),
                "outline_node_id": draft.outline_node_id,
                "draft_kind": str(draft.draft_kind or "new"),
                "target_chapter_id": draft.target_chapter_id,
                "status": "pending",
                "instruction_priority": "none",
            }
            if draft is not None else None
        ),
        "blocking_cataloging_job": (
            {
                "id": str(job.id),
                "status": job.status,
                "chapter_id": job.blocked_chapter_id or job.current_chapter_id,
            }
            if job is not None else None
        ),
        "cataloging_required_chapter": (
            {
                "id": str(chapter.id),
                "title": str(chapter.title or ""),
                "current_version": chapter.current_version,
                "cataloging_required": True,
            }
            if chapter is not None else None
        ),
    }
