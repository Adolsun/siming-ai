"""Natural idempotency keys and duplicate-write detection."""
from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from datetime import datetime
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...architecture.uow import commit_session
from ...database.models import (
    AssistantRun,
    AssistantRunStep,
    Chapter,
    ChapterWriteClaim,
    OperationRun,
)
from ..operation_runtime import current_operation_id


def generate_idempotency_key(
    db: Session,
    tool: str,
    project_id: str,
    args: dict,
) -> str | None:
    """Generate a stable key for idempotent workspace writes."""
    if tool == "create_chapter":
        key = str(args.get("outline_node_id") or args.get("title") or "").strip()
        return f"create_chapter:{project_id}:{key}" if key else None

    if tool == "update_chapter" and bool(args.get("rewrite")):
        target = str(
            args.get("chapter_id")
            or args.get("id")
            or args.get("outline_node_id")
            or args.get("title")
            or ""
        ).strip()
        request_id = str(
            args.get("rewrite_request_id")
            or args.get("draft_id")
            or args.get("content_ref")
            or ""
        ).strip()
        if not request_id and args.get("content") is not None:
            content_hash = hashlib.sha256(
                str(args.get("content") or "").encode("utf-8")
            ).hexdigest()[:16]
            expected_version = str(args.get("expected_version") or "").strip()
            request_id = f"{expected_version}:{content_hash}"
        return (
            f"rewrite_chapter:{project_id}:{target}:{request_id}"
            if target and request_id
            else None
        )

    if tool == "create_character":
        key = str(args.get("name") or "").strip()
        return f"create_character:{project_id}:{key}" if key else None

    if tool == "create_outline_node":
        parent = str(args.get("parent_id") or "").strip()
        title = str(args.get("title") or "").strip()
        key = f"{parent}:{title}" if parent else title
        return f"create_outline_node:{project_id}:{key}" if key else None

    if tool == "create_outline_nodes":
        nodes = args.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            return None
        natural_keys: list[str] = []
        default_parent = str(args.get("parent_id") or "").strip()
        for item in nodes[:8]:
            if not isinstance(item, dict):
                continue
            parent = str(item.get("parent_id") or default_parent).strip()
            title = str(item.get("title") or "").strip()
            if title:
                natural_keys.append(f"{parent}:{title}" if parent else title)
        if not natural_keys:
            return None
        digest = hashlib.sha256("|".join(natural_keys).encode("utf-8")).hexdigest()[:16]
        return f"create_outline_nodes:{project_id}:{digest}"

    if tool == "create_worldbuilding_entry":
        dimension = str(args.get("dimension") or "").strip()
        title = str(args.get("title") or "").strip()
        key = f"{dimension}:{title}"
        return f"create_worldbuilding_entry:{project_id}:{key}" if title else None

    if tool == "create_relationship":
        source = str(args.get("source") or args.get("from") or "").strip()
        target = str(args.get("target") or args.get("to") or "").strip()
        if not source or not target:
            return None
        from .utils import find_character_by_name_or_id

        source_character = find_character_by_name_or_id(db, project_id, source)
        target_character = find_character_by_name_or_id(db, project_id, target)
        if source_character and target_character:
            first, second = sorted([source_character.id, target_character.id])
            return f"create_relationship:{project_id}:{first}:{second}"
        first, second = sorted([source.lower(), target.lower()])
        return f"create_relationship:{project_id}:{first}:{second}"

    return None


def chapter_write_target_key(
    project_id: str,
    *,
    outline_node_id: object | None = None,
    chapter_id: object | None = None,
) -> str | None:
    """Return the durable mutex key for one logical chapter target."""
    outline = str(outline_node_id or "").strip()
    if outline:
        return f"project:{project_id}:outline:{outline}"
    chapter = str(chapter_id or "").strip()
    if chapter:
        return f"project:{project_id}:chapter:{chapter}"
    return None


def check_idempotency(
    db: Session,
    project_id: str,
    idempotency_key: str,
) -> dict | None:
    """Return a prior successful result for an identical write."""
    claim = (
        db.query(ChapterWriteClaim)
        .filter(
            ChapterWriteClaim.project_id == project_id,
            ChapterWriteClaim.idempotency_key == idempotency_key,
            ChapterWriteClaim.status == "completed",
        )
        .first()
    )
    if claim:
        chapter = (
            db.query(Chapter)
            .filter(Chapter.id == claim.chapter_id, Chapter.project_id == project_id)
            .first()
            if claim.chapter_id
            else None
        )
        if chapter and str(chapter.content or "").strip():
            result: dict = {}
            if claim.result_json:
                with suppress(Exception):
                    result = json.loads(claim.result_json)
            expected_tool = (
                "update_chapter"
                if idempotency_key.startswith("rewrite_chapter:")
                else "create_chapter"
            )
            result_data = result.get("data") if isinstance(result, dict) else None
            result_chapter_id = (
                str((result_data or {}).get("chapter_id") or (result_data or {}).get("id") or "")
                if isinstance(result_data, dict)
                else ""
            )
            if (
                not isinstance(result, dict)
                or not isinstance(result_data, dict)
                or (result_chapter_id and result_chapter_id != chapter.id)
            ):
                result = {}
            if not result:
                result = {
                    "tool": expected_tool,
                    "status": "ok",
                    "detail": (
                        "已完成，跳过重复重写"
                        if expected_tool == "update_chapter"
                        else "已存在，跳过重复创建"
                    ),
                    "data": {
                        "id": chapter.id,
                        "chapter_id": chapter.id,
                        "title": chapter.title,
                        "word_count": chapter.word_count or 0,
                    },
                }
            else:
                result = {
                    **result,
                    "tool": expected_tool,
                    "data": {
                        **result_data,
                        "id": chapter.id,
                        "chapter_id": chapter.id,
                        "title": chapter.title,
                        "word_count": chapter.word_count or 0,
                    },
                }
            replay_detail = (
                "已完成，跳过重复重写"
                if result.get("tool") == "update_chapter"
                else "已存在，跳过重复创建"
            )
            return {
                **result,
                "status": "ok",
                "detail": replay_detail,
                "data": {
                    **(result.get("data") or {}),
                    "idempotent_replay": True,
                },
            }

    existing = (
        db.query(AssistantRunStep)
        .filter(
            AssistantRunStep.project_id == project_id,
            AssistantRunStep.idempotency_key == idempotency_key,
            AssistantRunStep.status == "ok",
        )
        .order_by(AssistantRunStep.completed_at.desc())
        .first()
    )
    if not existing:
        return None

    result = {}
    if existing.result_json:
        with suppress(Exception):
            result = json.loads(existing.result_json)
    if not isinstance(result, dict):
        return None
    if (
        existing.tool in {"create_chapter", "update_chapter"}
        or idempotency_key.startswith(("create_chapter:", "rewrite_chapter:"))
    ):
        data = result.get("data") if isinstance(result, dict) else None
        chapter_id = (
            str((data or {}).get("chapter_id") or (data or {}).get("id") or "").strip()
            if isinstance(data, dict)
            else ""
        )
        chapter = (
            db.query(Chapter)
            .filter(Chapter.id == chapter_id, Chapter.project_id == project_id)
            .first()
            if chapter_id
            else None
        )
        if not chapter or not str(chapter.content or "").strip():
            return None
    return {
        "tool": existing.tool or "",
        "status": "ok",
        "detail": "已存在，跳过重复创建",
        "data": result.get("data"),
    }


def _claim_owner(db: Session) -> tuple[str | None, str | None]:
    operation_id = current_operation_id()
    if not operation_id:
        return None, None
    run = (
        db.query(AssistantRun)
        .filter(AssistantRun.operation_id == operation_id)
        .order_by(AssistantRun.created_at.desc())
        .first()
    )
    return (run.id if run else None), operation_id


def _active_claim_result(claim: ChapterWriteClaim) -> dict:
    is_rewrite = claim.idempotency_key.startswith("rewrite_chapter:")
    return {
        "state": "running",
        "claim_id": claim.id,
        "result": {
            "tool": "update_chapter" if is_rewrite else "create_chapter",
            "status": "blocked",
            "detail": (
                "同一次章节重写仍在执行，未重复写入"
                if is_rewrite
                else "同一章节已有写作任务，未重复创建"
            ),
            "data": {
                "run_id": claim.run_id,
                "operation_id": claim.operation_id,
                "target_key": claim.target_key,
            },
        },
    }


def _new_claim_token() -> str:
    return str(uuid4())


def acquire_chapter_write_claim(
    db: Session,
    *,
    project_id: str,
    target_key: str,
    idempotency_key: str,
) -> dict:
    """Atomically reserve one logical chapter write across concurrent assistant runs."""
    target_key = str(target_key or "").strip()
    if not target_key:
        raise ValueError("章节写作占用缺少目标")
    owner_run_id, operation_id = _claim_owner(db)
    for attempt in range(4):
        now = datetime.utcnow()
        request_claim = (
            db.query(ChapterWriteClaim)
            .filter(
                ChapterWriteClaim.project_id == project_id,
                ChapterWriteClaim.idempotency_key == idempotency_key,
            )
            .first()
        )
        if request_claim:
            if request_claim.status == "completed":
                existing = check_idempotency(db, project_id, idempotency_key)
                if existing:
                    return {
                        "state": "completed",
                        "claim_id": request_claim.id,
                        "claim_token": None,
                        "result": existing,
                    }
            elif request_claim.status == "running":
                same_owner = bool(
                    (operation_id and request_claim.operation_id == operation_id)
                    or (owner_run_id and request_claim.run_id == owner_run_id)
                )
                if same_owner:
                    return {
                        "state": "acquired",
                        "claim_id": request_claim.id,
                        "claim_token": request_claim.claim_token,
                        "result": None,
                    }
                return _active_claim_result(request_claim)

        active_target = (
            db.query(ChapterWriteClaim)
            .filter(
                ChapterWriteClaim.project_id == project_id,
                ChapterWriteClaim.target_key == target_key,
                ChapterWriteClaim.status == "running",
            )
            .first()
        )
        if active_target:
            same_owner = bool(
                (operation_id and active_target.operation_id == operation_id)
                or (owner_run_id and active_target.run_id == owner_run_id)
            )
            if same_owner:
                return {
                    "state": "acquired",
                    "claim_id": active_target.id,
                    "claim_token": active_target.claim_token,
                    "result": None,
                }
            return _active_claim_result(active_target)

        if request_claim:
            previous_status = request_claim.status
            previous_token = request_claim.claim_token
            next_token = _new_claim_token()
            result = db.execute(
                update(ChapterWriteClaim)
                .where(
                    ChapterWriteClaim.id == request_claim.id,
                    ChapterWriteClaim.status == previous_status,
                    ChapterWriteClaim.claim_token == previous_token,
                )
                .values(
                    target_key=target_key,
                    status="running",
                    claim_token=next_token,
                    run_id=owner_run_id,
                    operation_id=operation_id,
                    chapter_id=None,
                    result_json=None,
                    error=None,
                    completed_at=None,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                db.rollback()
                db.expire_all()
                continue
            try:
                commit_session(db)
            except IntegrityError:
                db.rollback()
                db.expire_all()
                if attempt == 3:
                    raise
                continue
            return {
                "state": "acquired",
                "claim_id": request_claim.id,
                "claim_token": next_token,
                "result": None,
            }
        else:
            next_token = _new_claim_token()
            claim = ChapterWriteClaim(
                project_id=project_id,
                target_key=target_key,
                idempotency_key=idempotency_key,
                claim_token=next_token,
                status="running",
                run_id=owner_run_id,
                operation_id=operation_id,
                created_at=now,
                updated_at=now,
            )
            db.add(claim)
        try:
            commit_session(db)
            db.refresh(claim)
            return {
                "state": "acquired",
                "claim_id": claim.id,
                "claim_token": claim.claim_token,
                "result": None,
            }
        except IntegrityError:
            db.rollback()
            db.expire_all()
            if attempt == 3:
                raise

    raise RuntimeError("无法建立章节写作占用")


def validate_chapter_write_claim(
    db: Session,
    *,
    project_id: str,
    target_key: str,
    idempotency_key: str,
    claim_id: str | None,
    claim_token: str | None,
) -> bool:
    """Validate a claim already fenced by the plan before its save step."""
    if not claim_id or not claim_token:
        return False
    return db.query(ChapterWriteClaim).filter(
        ChapterWriteClaim.id == claim_id,
        ChapterWriteClaim.project_id == project_id,
        ChapterWriteClaim.target_key == target_key,
        ChapterWriteClaim.idempotency_key == idempotency_key,
        ChapterWriteClaim.claim_token == claim_token,
        ChapterWriteClaim.status == "running",
    ).first() is not None


def complete_chapter_write_claim(
    db: Session,
    claim_id: str | None,
    claim_token: str | None,
    *,
    chapter_id: str,
    result: dict,
) -> bool:
    if not claim_id:
        return True
    if not claim_token:
        return False
    now = datetime.utcnow()
    updated = db.execute(
        update(ChapterWriteClaim)
        .where(
            ChapterWriteClaim.id == claim_id,
            ChapterWriteClaim.claim_token == claim_token,
            ChapterWriteClaim.status == "running",
            or_(
                ChapterWriteClaim.operation_id.is_(None),
                ChapterWriteClaim.operation_id.in_(
                    select(OperationRun.id).where(
                        OperationRun.status.in_(("queued", "running"))
                    )
                ),
            ),
        )
        .values(
            status="completed",
            chapter_id=chapter_id,
            result_json=json.dumps(result, ensure_ascii=False, default=str),
            error=None,
            updated_at=now,
            completed_at=now,
        )
    )
    return updated.rowcount == 1


def fail_chapter_write_claim(
    db: Session,
    claim_id: str | None,
    claim_token: str | None,
    *,
    status: str = "failed",
    error: str | None = None,
) -> bool:
    if not claim_id:
        return True
    if not claim_token:
        return False
    now = datetime.utcnow()
    updated = db.execute(
        update(ChapterWriteClaim)
        .where(
            ChapterWriteClaim.id == claim_id,
            ChapterWriteClaim.claim_token == claim_token,
            ChapterWriteClaim.status == "running",
        )
        .values(
            status="cancelled" if status == "cancelled" else "failed",
            error=(error or "章节写作未完成")[:2000],
            updated_at=now,
            completed_at=now,
        )
    )
    commit_session(db)
    return updated.rowcount == 1


def mark_interrupted_chapter_write_claims(db: Session) -> int:
    claims = db.query(ChapterWriteClaim).filter(ChapterWriteClaim.status == "running").all()
    now = datetime.utcnow()
    for claim in claims:
        claim.status = "failed"
        claim.error = "应用关闭或服务重启时章节写作尚未完成，可安全重试"
        claim.updated_at = now
        claim.completed_at = now
    if claims:
        db.flush()
    return len(claims)


__all__ = [
    "acquire_chapter_write_claim",
    "chapter_write_target_key",
    "check_idempotency",
    "complete_chapter_write_claim",
    "fail_chapter_write_claim",
    "generate_idempotency_key",
    "mark_interrupted_chapter_write_claims",
    "validate_chapter_write_claim",
]
