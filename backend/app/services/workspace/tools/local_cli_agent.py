"""Workspace tool to launch a local CLI agent worker."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ....core.utils import count_words
from ....database.models import AgentRun, AgentRunEvent, Chapter, ChapterDraft, Project
from ....services.storage_contract import storage_health
from ....services.local_cli_agent_worker import start_local_cli_agent_worker
from ....services.operation_runtime import current_operation_id
from ..idempotency import (
    acquire_chapter_write_claim,
    chapter_write_target_key,
    fail_chapter_write_claim,
    validate_chapter_write_claim,
)
from ..utils import find_outline_by_title_or_id


_TERMINAL_RUN_STATES = {"completed", "failed", "cancelled"}


def _run_data(run: AgentRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "status": run.status,
        "summary": run.summary,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _recent_events(db: Session, run_id: str, limit: int = 5) -> list[dict[str, Any]]:
    events = (
        db.query(AgentRunEvent)
        .filter(AgentRunEvent.run_id == run_id)
        .order_by(AgentRunEvent.sequence.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "status": event.status,
            "message": event.message,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in reversed(events)
    ]


def _validate_writing_result(
    db: Session,
    project_id: str,
    run: AgentRun,
    args: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    outline_node_id = str(args.get("outline_node_id") or "").strip()
    project = db.query(Project).filter(Project.id == project_id).first()
    since = run.created_at or datetime.utcnow()

    query = db.query(Chapter).filter(Chapter.project_id == project_id)
    if outline_node_id:
        query = query.filter(
            Chapter.outline_node_id == outline_node_id,
            (Chapter.created_at >= since) | (Chapter.updated_at >= since),
        )
    else:
        query = query.filter(
            (Chapter.created_at >= since) | (Chapter.updated_at >= since)
        )
    chapters = query.order_by(Chapter.updated_at.desc(), Chapter.created_at.desc()).limit(5).all()
    data: dict[str, Any] = {
        "chapters": [
            {
                "chapter_id": chapter.id,
                "title": chapter.title,
                "outline_node_id": chapter.outline_node_id,
                "word_count": chapter.word_count or 0,
                "content_file_path": chapter.content_file_path,
                "updated_at": chapter.updated_at.isoformat() if chapter.updated_at else None,
            }
            for chapter in chapters
        ],
    }
    if chapters:
        return True, f"本机 CLI 写作已入库：{chapters[0].title}", data

    drafts = (
        db.query(ChapterDraft)
        .filter(ChapterDraft.project_id == project_id, ChapterDraft.created_at >= since)
        .order_by(ChapterDraft.created_at.desc())
        .limit(5)
        .all()
    )
    data["drafts"] = [
        {
            "draft_id": draft.id,
            "title": draft.title,
            "outline_node_id": draft.outline_node_id,
            "word_count": count_words(draft.content or ""),
            "created_at": draft.created_at.isoformat() if draft.created_at else None,
        }
        for draft in drafts
    ]
    storage = storage_health(db, project, since=since) if project else {}
    data["storage_health"] = storage
    data["orphan_chapter_files"] = storage.get("orphan_chapter_files", [])
    if data["orphan_chapter_files"]:
        detail = "本机 CLI 已结束，但没有发现章节写入数据库；检测到未入库的章节镜像文件，请显式修复导入或重试。"
    elif data["drafts"]:
        detail = "本机 CLI 只保存了章节草稿，但没有调用 create_chapter 入库；请重试或用草稿创建章节。"
    else:
        detail = "本机 CLI 已结束，但没有发现章节草稿或章节入库记录。"
    data["repair_hint"] = "镜像目录不是权威数据源；修复时请显式调用 sync_project_files(direction='import', confirm_import_from_files=true)，或重新通过 create_chapter 入库。"
    return False, detail, data


async def start_local_cli_agent_run(
    db: Session,
    project_id: str,
    args: dict[str, Any],
) -> dict:
    """Start Claude/Codex/opencode as a Siming-managed CLI Agent worker."""
    if str(args.get("_context_execution_route") or "").strip() == "external_mcp":
        return {
            "tool": "start_local_cli_agent_run",
            "status": "skipped",
            "detail": (
                "当前已经在外部 MCP Agent 中，不能递归启动第二个 CLI。"
                "请使用 prepare_external_writing_context、start_agent_run、"
                "report_context_selected 和写入工具完成当前任务。"
            ),
            "data": None,
        }
    task_type = str(args.get("task_type") or args.get("mode") or "general").strip().lower()
    if task_type not in {"general", "cataloging", "writing"}:
        task_type = "general"
    user_request = str(args.get("user_request") or args.get("request") or "").strip()
    provider = str(args.get("provider") or "").strip() or None
    rewrite = bool(args.get("rewrite"))
    outline_node_id = str(args.get("outline_node_id") or "").strip()
    claim_id = str(args.get("_chapter_claim_id") or "").strip() or None
    claim_token = str(args.get("_chapter_claim_token") or "").strip() or None
    claim_target_key = str(args.get("_chapter_target_key") or "").strip()
    claim_idempotency_key = str(args.get("_chapter_idempotency_key") or "").strip()
    parent_operation_id = (
        str(args.get("parent_operation_id") or "").strip()
        or current_operation_id()
    )

    if task_type == "writing":
        outline = find_outline_by_title_or_id(
            db,
            project_id,
            outline_node_id,
            node_type="chapter",
        )
        if not outline:
            return {
                "tool": "start_local_cli_agent_run",
                "status": "error",
                "detail": "本机 CLI 写作缺少当前作品中的章节大纲，本轮未启动。",
                "data": None,
            }
        outline_node_id = outline.id
        claim_target_key = claim_target_key or chapter_write_target_key(
            project_id,
            outline_node_id=outline.id,
        ) or ""
        claim_idempotency_key = claim_idempotency_key or (
            f"rewrite_chapter:{project_id}:{outline.id}:{parent_operation_id or 'direct'}"
            if rewrite
            else f"create_chapter:{project_id}:{outline.id}"
        )
        if claim_id or claim_token:
            if not validate_chapter_write_claim(
                db,
                project_id=project_id,
                target_key=claim_target_key,
                idempotency_key=claim_idempotency_key,
                claim_id=claim_id,
                claim_token=claim_token,
            ):
                return {
                    "tool": "start_local_cli_agent_run",
                    "status": "error",
                    "detail": "章节写作占用已失效，本机 CLI 未启动，请重新执行任务。",
                    "data": None,
                }
        else:
            reservation = acquire_chapter_write_claim(
                db,
                project_id=project_id,
                target_key=claim_target_key,
                idempotency_key=claim_idempotency_key,
            )
            if reservation.get("state") != "acquired":
                existing = reservation.get("result") or {}
                return {
                    "tool": "start_local_cli_agent_run",
                    "status": "ok" if reservation.get("state") == "completed" else "blocked",
                    "detail": str(existing.get("detail") or "同一章节已有写作任务，未重复启动本机 CLI。"),
                    "data": existing.get("data"),
                }
            claim_id = str(reservation.get("claim_id") or "").strip() or None
            claim_token = str(reservation.get("claim_token") or "").strip() or None

    context_arguments = {
        "outline_node_id": outline_node_id,
        "chapter_id": str(args.get("chapter_id") or "").strip(),
        "requirements": user_request,
        "pinned_chunk_ids": args.get("pinned_chunk_ids") if isinstance(args.get("pinned_chunk_ids"), list) else [],
        "pinned_source_ids": args.get("pinned_source_ids") if isinstance(args.get("pinned_source_ids"), list) else [],
        "rewrite": rewrite,
        "managed_chapter_write": bool(task_type == "writing" and claim_id and claim_token),
        "parent_plan_id": str(args.get("parent_plan_id") or "").strip(),
        "parent_operation_id": parent_operation_id or "",
        "chapter_claim_id": claim_id or "",
        "chapter_claim_token": claim_token or "",
        "chapter_target_key": claim_target_key,
        "chapter_idempotency_key": claim_idempotency_key,
    }
    try:
        result = start_local_cli_agent_worker(
            db,
            project_id,
            user_request=user_request,
            task_type=task_type,
            provider=provider,
            context_manifest_id=str(args.get("context_manifest_id") or "").strip() or None,
            context_arguments=context_arguments,
        )
    except BaseException:
        if task_type == "writing":
            fail_chapter_write_claim(
                db,
                claim_id,
                claim_token,
                error="本机 CLI 启动异常，已释放章节写作占用",
            )
        raise
    if task_type == "writing" and result.get("status") != "ok":
        fail_chapter_write_claim(
            db,
            claim_id,
            claim_token,
            error=str(result.get("detail") or "本机 CLI 未启动"),
        )
    return {
        "tool": "start_local_cli_agent_run",
        "status": result.get("status", "ok"),
        "detail": result.get("detail", ""),
        "data": result.get("data"),
    }


async def wait_local_cli_agent_run(
    db: Session,
    project_id: str,
    args: dict[str, Any],
) -> dict:
    """Wait for a Siming-managed local CLI run and validate the requested outcome."""
    run_id = str(args.get("run_id") or "").strip()
    if not run_id or run_id.startswith("{"):
        return {"tool": "wait_local_cli_agent_run", "status": "error", "detail": "本机 CLI 没有成功启动，未获得 run_id", "data": None}

    timeout_seconds = max(1, min(int(args.get("timeout_seconds") or 1800), 7200))
    startup_timeout_seconds = max(1, min(int(args.get("startup_timeout_seconds") or 10), timeout_seconds))
    poll_seconds = max(0.5, min(float(args.get("poll_seconds") or 2), 10))
    task_type = str(args.get("task_type") or args.get("mode") or "").strip().lower()
    started = time.monotonic()

    run: AgentRun | None = None
    while True:
        db.expire_all()
        run = (
            db.query(AgentRun)
            .filter(AgentRun.id == run_id, AgentRun.project_id == project_id)
            .first()
        )
        if not run:
            return {"tool": "wait_local_cli_agent_run", "status": "skipped", "detail": "未找到本机 CLI 运行记录", "data": None}
        if run.status in _TERMINAL_RUN_STATES:
            break
        if run.status == "created" and time.monotonic() - started >= startup_timeout_seconds:
            return {
                "tool": "wait_local_cli_agent_run",
                "status": "error",
                "detail": f"本机 CLI 未在 {startup_timeout_seconds} 秒内开始运行；请检查 CLI 命令、登录状态和 MCP 配置",
                "data": {"run": _run_data(run), "events": _recent_events(db, run_id)},
            }
        if time.monotonic() - started >= timeout_seconds:
            return {
                "tool": "wait_local_cli_agent_run",
                "status": "error",
                "detail": f"本机 CLI 仍在运行，等待超过 {timeout_seconds} 秒；请在运行记录中查看进度",
                "data": {"run": _run_data(run), "events": _recent_events(db, run_id)},
            }
        await asyncio.sleep(poll_seconds)

    data: dict[str, Any] = {"run": _run_data(run), "events": _recent_events(db, run_id)}
    if run.status != "completed":
        return {
            "tool": "wait_local_cli_agent_run",
            "status": "error",
            "detail": run.summary or f"本机 CLI 运行失败：{run.status}",
            "data": data,
        }

    if task_type == "writing":
        ok, detail, validation = _validate_writing_result(db, project_id, run, args)
        data["validation"] = validation
        return {
            "tool": "wait_local_cli_agent_run",
            "status": "ok" if ok else "error",
            "detail": detail,
            "data": data,
        }

    return {
        "tool": "wait_local_cli_agent_run",
        "status": "ok",
        "detail": "本机 CLI 运行完成",
        "data": data,
    }
