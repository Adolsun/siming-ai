"""Project management workspace tools."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ....database.models import Project
from ....modules.story.application.content_sync import queue_content_sync
from ....modules.story.domain.content_sync import ContentSyncIntent, ContentSyncTarget
from ...project_creation_context import (
    ensure_project_creation_session,
    get_project_creation_context,
    resolve_project_creation_session,
)


def _project_payload(project: Project) -> dict:
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "tags": project.tags,
        "narrative_perspective": project.narrative_perspective,
        "writing_style": project.writing_style,
        "forbidden_sentence_patterns": project.forbidden_sentence_patterns,
        "rhetoric_guidelines": project.rhetoric_guidelines,
        "short_sentences": bool(project.short_sentences),
        "custom_style_prompt": project.custom_style_prompt,
        "daily_word_goal": project.daily_word_goal,
        "storage_mode": getattr(project, "storage_mode", None),
        "folder_path": getattr(project, "folder_path", None),
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def _tags_to_json(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return json.dumps([str(item) for item in value if str(item).strip()], ensure_ascii=False)
    text = str(value).strip()
    if not text:
        return None
    parts = [part.strip() for part in text.replace("，", ",").split(",") if part.strip()]
    return json.dumps(parts, ensure_ascii=False)


async def list_projects(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    query_text = str(args.get("query") or args.get("q") or "").strip()
    query = db.query(Project)
    if query_text:
        keyword = f"%{query_text}%"
        query = query.filter(or_(Project.title.like(keyword), Project.description.like(keyword)))
    projects = query.order_by(Project.updated_at.desc()).limit(int(args.get("limit") or 50)).all()
    return {
        "tool": "list_projects",
        "status": "ok",
        "detail": f"共找到 {len(projects)} 个作品",
        "data": {
            "items": [_project_payload(project) for project in projects],
            "total": len(projects),
            "current_project_id": project_id,
        },
    }


async def get_project_info(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    target_id = str(args.get("id") or args.get("project_id") or project_id).strip()
    project = db.query(Project).filter(Project.id == target_id).first()
    if not project:
        return {"tool": "get_project_info", "status": "skipped", "detail": "未找到作品"}
    data = _project_payload(project)
    creation = get_project_creation_context(db, target_id)
    if creation:
        data["creation"] = creation
    return {
        "tool": "get_project_info",
        "status": "ok",
        "detail": f"已读取作品：{project.title}",
        "data": data,
    }


async def get_project_creation_brief(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    """Read creative direction, constraints, style and their source status."""
    target_id = str(args.get("project_id") or args.get("id") or project_id).strip()
    project = db.get(Project, target_id)
    if project is None:
        return {"tool": "get_project_creation_brief", "status": "skipped", "detail": "未找到作品"}
    session = resolve_project_creation_session(db, target_id)
    context = get_project_creation_context(db, target_id)
    return {
        "tool": "get_project_creation_brief",
        "status": "ok",
        "detail": "已读取作品立项资料" if session else "作品尚未建立立项资料，可在用户要求修改或回填时创建",
        "data": {
            "project_id": target_id,
            "creation_session_id": session.id if session else None,
            "creation": context,
        },
    }


async def update_project_creation_brief(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    """Create or patch the authoritative brief for a formal project."""
    from app.services.novel_creation_workspace import patch_creation_artifact, serialize_creation_artifact

    target_id = str(args.get("project_id") or args.get("id") or project_id).strip()
    project = db.get(Project, target_id)
    if project is None:
        return {"tool": "update_project_creation_brief", "status": "skipped", "detail": "未找到作品"}
    session = ensure_project_creation_session(db, target_id)
    expected_revision = args.get("expected_revision")
    if expected_revision is not None and int(expected_revision) != int(session.revision or 0):
        return {
            "tool": "update_project_creation_brief",
            "status": "needs_confirmation",
            "detail": "立项资料已被其他操作更新，请重新读取后再修改",
            "data": {"revision": int(session.revision or 0), "creation_session_id": session.id},
        }

    changed_artifacts: list[str] = []
    constraints = args.get("constraints") if isinstance(args.get("constraints"), dict) else {}
    if constraints:
        current = serialize_creation_artifact(session, "constraints").get("data") or {}
        merged = {**dict(current), **constraints}
        patch_creation_artifact(
            session,
            "constraints",
            [{"path": "/", "action": "replace", "value": merged}],
            source="project_assistant",
        )
        changed_artifacts.append("constraints")
        writing_style = str(constraints.get("writing_style") or "").strip()
        if writing_style:
            project.custom_style_prompt = writing_style

    creative = args.get("creative_direction") if isinstance(args.get("creative_direction"), dict) else {}
    if creative:
        current = serialize_creation_artifact(session, "concepts").get("data") or {}
        options = [dict(item) for item in current.get("options", []) if isinstance(item, dict)]
        selected_id = str(
            creative.get("selected_concept_id")
            or current.get("selected_concept_id")
            or (options[0].get("id") if options else "project-concept-1")
        )
        selected_patch = creative.get("selected") if isinstance(creative.get("selected"), dict) else {
            key: value
            for key, value in creative.items()
            if key not in {"selected_concept_id", "options"}
        }
        supplied_options = creative.get("options")
        if isinstance(supplied_options, list):
            options = [dict(item) for item in supplied_options if isinstance(item, dict)]
        if selected_patch:
            matched = False
            for index, option in enumerate(options):
                if str(option.get("id") or "") == selected_id:
                    options[index] = {**option, **selected_patch, "id": selected_id}
                    matched = True
                    break
            if not matched:
                options.insert(0, {"id": selected_id, **selected_patch})
        concept_data = {**dict(current), "options": options, "selected_concept_id": selected_id}
        patch_creation_artifact(
            session,
            "concepts",
            [{"path": "/", "action": "replace", "value": concept_data}],
            source="project_assistant",
        )
        changed_artifacts.append("concepts")

    world_style = args.get("world_style") if isinstance(args.get("world_style"), dict) else {}
    if world_style:
        current = serialize_creation_artifact(session, "world_style").get("data") or {}
        patch_creation_artifact(
            session,
            "world_style",
            [{"path": "/", "action": "replace", "value": {**dict(current), **world_style}}],
            source="project_assistant",
        )
        changed_artifacts.append("world_style")

    if not changed_artifacts:
        return {
            "tool": "update_project_creation_brief",
            "status": "skipped",
            "detail": "没有提供可修改的创作约束、创意方向或文风与世界观",
        }
    project.updated_at = datetime.utcnow()
    queue_content_sync(
        db,
        ContentSyncIntent(
            project_id=project.id,
            target=ContentSyncTarget.PROJECT_MANIFEST,
            entity_id=project.id,
            source="project_creation_brief",
        ),
    )
    db.flush()
    return {
        "tool": "update_project_creation_brief",
        "status": "ok",
        "detail": f"已更新作品立项资料：{'、'.join(changed_artifacts)}",
        "data": {
            "project_id": target_id,
            "creation_session_id": session.id,
            "revision": int(session.revision or 0),
            "changed_artifacts": changed_artifacts,
            "creation": get_project_creation_context(db, target_id, session.id),
        },
    }


async def create_project(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    title = str(args.get("title") or "").strip()
    if not title:
        return {"tool": "create_project", "status": "skipped", "detail": "作品标题为空"}

    from ..idempotency import check_idempotency, generate_idempotency_key

    idem_key = generate_idempotency_key(db, "create_project", project_id, args)
    if idem_key:
        existing = check_idempotency(db, project_id, idem_key)
        if existing:
            return existing

    project = Project(
        title=title[:200],
        description=str(args.get("description") or "") or None,
        tags=_tags_to_json(args.get("tags")),
        narrative_perspective=str(args.get("narrative_perspective") or "third_person")[:50],
        writing_style=str(args.get("writing_style") or "natural")[:50],
        forbidden_sentence_patterns=str(args.get("forbidden_sentence_patterns") or "") or None,
        rhetoric_guidelines=str(args.get("rhetoric_guidelines") or "") or None,
        short_sentences=bool(args.get("short_sentences") or False),
        custom_style_prompt=str(args.get("custom_style_prompt") or "") or None,
        daily_word_goal=int(args.get("daily_word_goal") or 6000),
    )
    db.add(project)
    db.flush()
    queue_content_sync(
        db,
        ContentSyncIntent(
            project_id=project.id,
            target=ContentSyncTarget.PROJECT,
            entity_id=project.id,
            source="workspace_tool",
        ),
    )
    return {
        "tool": "create_project",
        "status": "ok",
        "detail": f"已创建作品：{project.title}",
        "data": _project_payload(project),
    }


async def update_project_info(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    target_id = str(args.get("id") or args.get("project_id") or project_id).strip()
    project = db.query(Project).filter(Project.id == target_id).first()
    if not project:
        return {"tool": "update_project_info", "status": "skipped", "detail": "未找到作品"}

    fields = {
        "title": 200,
        "description": None,
        "narrative_perspective": 50,
        "writing_style": 50,
        "forbidden_sentence_patterns": None,
        "rhetoric_guidelines": None,
        "custom_style_prompt": None,
    }
    changed = False
    for field, limit in fields.items():
        if field in args:
            value = str(args.get(field) or "")
            setattr(project, field, value[:limit] if limit else (value or None))
            changed = True
    if "tags" in args:
        project.tags = _tags_to_json(args.get("tags"))
        changed = True
    if "short_sentences" in args:
        project.short_sentences = bool(args.get("short_sentences"))
        changed = True
    if "daily_word_goal" in args and args.get("daily_word_goal") is not None:
        project.daily_word_goal = max(0, int(args.get("daily_word_goal")))
        changed = True
    if changed:
        project.updated_at = datetime.utcnow()
        queue_content_sync(
            db,
            ContentSyncIntent(
                project_id=project.id,
                target=ContentSyncTarget.PROJECT_MANIFEST,
                entity_id=project.id,
                source="workspace_tool",
            ),
        )
    return {
        "tool": "update_project_info",
        "status": "ok",
        "detail": f"已更新作品：{project.title}",
        "data": _project_payload(project),
    }


async def delete_project(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    target_id = str(args.get("id") or args.get("project_id") or "").strip()
    if not target_id:
        return {"tool": "delete_project", "status": "skipped", "detail": "缺少要删除的作品ID"}
    project = db.query(Project).filter(Project.id == target_id).first()
    if not project:
        return {"tool": "delete_project", "status": "skipped", "detail": "未找到作品"}
    title = project.title
    folder_path = project.folder_path
    db.delete(project)
    queue_content_sync(
        db,
        ContentSyncIntent(
            project_id=target_id,
            target=ContentSyncTarget.PROJECT_DELETE,
            entity_id=target_id,
            payload={"folder_path": folder_path},
            source="workspace_tool",
        ),
    )
    return {"tool": "delete_project", "status": "ok", "detail": f"已删除作品：{title}", "data": {"id": target_id}}
