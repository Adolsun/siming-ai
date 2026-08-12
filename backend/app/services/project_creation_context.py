"""Resolve the authoritative creation brief linked to a real project."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database.models import NovelCreationSession, Project


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def resolve_project_creation_session(
    db: Session,
    project_id: str,
    requested_session_id: str | None = None,
) -> NovelCreationSession | None:
    """Return the one creation session that is authoritative for a project.

    A session that created the project always wins.  ``source_project_id`` is
    only a fallback for an in-place draft; a session that used one project as
    inspiration but created a different project must not leak into the source.
    """

    project_id = str(project_id or "").strip()
    requested_session_id = str(requested_session_id or "").strip()
    if not project_id:
        return None

    def belongs(session: NovelCreationSession | None) -> bool:
        if session is None:
            return False
        if session.created_project_id == project_id:
            return True
        return session.source_project_id == project_id and not session.created_project_id

    if requested_session_id:
        requested = (
            db.query(NovelCreationSession)
            .filter(NovelCreationSession.id == requested_session_id)
            .first()
        )
        if belongs(requested):
            return requested

    created = (
        db.query(NovelCreationSession)
        .filter(NovelCreationSession.created_project_id == project_id)
        .order_by(
            NovelCreationSession.completed_at.desc(),
            NovelCreationSession.updated_at.desc(),
            NovelCreationSession.created_at.desc(),
        )
        .first()
    )
    if created:
        return created
    return (
        db.query(NovelCreationSession)
        .filter(
            NovelCreationSession.source_project_id == project_id,
            or_(
                NovelCreationSession.created_project_id.is_(None),
                NovelCreationSession.created_project_id == "",
            ),
        )
        .order_by(
            NovelCreationSession.updated_at.desc(),
            NovelCreationSession.created_at.desc(),
        )
        .first()
    )


def ensure_project_creation_session(db: Session, project_id: str) -> NovelCreationSession:
    """Return or create the editable creation brief for a formal project.

    Imported and legacy projects did not necessarily pass through novel
    creation.  Creating a first-class session for them gives authors and the
    project assistant one consistent place to maintain creative direction,
    constraints, and style without rewriting chapters or other business data.
    """
    existing = resolve_project_creation_session(db, project_id)
    if existing is not None:
        return existing
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("作品不存在")

    from app.services.novel_creation_workspace import initialize_session_draft

    brief = str(project.description or project.title or "").strip()
    writing_style = str(project.custom_style_prompt or "").strip()
    if not writing_style and str(project.writing_style or "").strip() not in {"", "natural"}:
        writing_style = str(project.writing_style).strip()
    special_requirements = [
        text
        for text in (
            str(project.rhetoric_guidelines or "").strip(),
            str(project.forbidden_sentence_patterns or "").strip(),
        )
        if text
    ]
    session = NovelCreationSession(
        source_project_id=project.id,
        created_project_id=project.id,
        status="completed",
        mode="internal_llm",
        user_brief=brief or None,
    )
    db.add(session)
    initialize_session_draft(session, {
        "brief": brief,
        "user_brief": brief,
        "creation_mode": "author_led",
        "author_brief": brief,
        "writing_style": writing_style,
        "special_requirements": special_requirements,
    })
    return session


def project_creation_context(session: NovelCreationSession | None) -> dict[str, Any] | None:
    """Build a compact, structured brief suitable for prompts, tools and files."""

    if session is None:
        return None
    draft = _dict(session.draft_json)
    stages = _dict(draft.get("stages"))
    form = _dict(draft.get("form"))
    constraints = _dict(stages.get("constraints"))
    if constraints.get("status") == "confirmed":
        form.update(deepcopy(_dict(constraints.get("data"))))

    concepts = _dict(_dict(stages.get("concepts")).get("data"))
    selected_id = str(
        concepts.get("selected_concept_id")
        or draft.get("selected_concept_id")
        or ""
    ).strip()
    options = [_dict(item) for item in _list(concepts.get("options"))]
    selected = next(
        (item for item in options if str(item.get("id") or "") == selected_id),
        options[0] if options else {},
    )
    statuses = {
        key: str(_dict(value).get("status") or "pending")
        for key, value in stages.items()
        if isinstance(value, dict)
    }
    confirmed = [key for key, status in statuses.items() if status == "confirmed"]
    pending = [
        key
        for key, status in statuses.items()
        if status in {"pending", "generated", "stale"}
    ]
    constraints_payload = {
        key: deepcopy(form.get(key))
        for key in (
            "brief",
            "preset_id",
            "theme_id",
            "genre",
            "target_audience",
            "platform",
            "target_words",
            "target_chapters",
            "opening_chapters",
            "world_tone",
            "story_structure",
            "pacing",
            "writing_style",
            "special_requirements",
            "avoid",
            "author_overrides",
        )
        if form.get(key) not in (None, "", [], {})
    }
    world_style = deepcopy(_dict(_dict(stages.get("world_style")).get("data")))
    creative_direction = {
        "selected_concept_id": selected_id or None,
        "selected": {
            key: deepcopy(selected.get(key))
            for key in (
                "id", "title", "logline", "premise", "genre", "subtitle",
                "world_hook", "core_conflict", "story_engine", "opening_hook",
                "differentiators", "risks",
            )
            if selected.get(key) not in (None, "", [], {})
        },
        "options": deepcopy(options),
    }
    return {
        "source_of_truth": "novel_creation_session",
        "creation_session_id": session.id,
        "created_project_id": session.created_project_id,
        "status": session.status,
        "revision": int(session.revision or 0),
        "constraints": constraints_payload,
        "selected_concept": {
            key: deepcopy(selected.get(key))
            for key in ("id", "title", "logline", "premise", "genre", "subtitle")
            if selected.get(key) not in (None, "", [], {})
        },
        "creative_direction": creative_direction,
        "world_style": world_style,
        "artifact_statuses": statuses,
        "confirmed_artifacts": confirmed,
        "pending_artifacts": pending,
    }


def get_project_creation_context(
    db: Session,
    project_id: str,
    requested_session_id: str | None = None,
) -> dict[str, Any] | None:
    return project_creation_context(
        resolve_project_creation_session(db, project_id, requested_session_id)
    )


__all__ = [
    "ensure_project_creation_session",
    "get_project_creation_context",
    "project_creation_context",
    "resolve_project_creation_session",
]
