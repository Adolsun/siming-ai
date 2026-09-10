"""Persisted cataloging state and SSE projections, independent of workers."""
from __future__ import annotations

import json
from typing import Any

from app.core.utils import utc_isoformat
from app.database.models import CatalogingChapterRun, CatalogingJob

_COVERAGE_REVIEW_PREFIX = "候选已保留，需要核对模型抽取的原文线索："


def sse_event(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _job_review_warning(job: CatalogingJob) -> str | None:
    chapter_id = job.blocked_chapter_id or job.current_chapter_id
    if not chapter_id:
        return None
    run = next((item for item in job.chapter_runs if item.chapter_id == chapter_id), None)
    return str(getattr(run, "review_warning", "") or "").strip() or None


def _promote_legacy_review_warning(run: CatalogingChapterRun) -> bool:
    """Move review-only diagnostics out of the hard-error channel."""

    error = str(run.error or "").strip()
    if not error.startswith(_COVERAGE_REVIEW_PREFIX):
        return False
    run.review_warning = error
    run.error = None
    return True


def job_to_dict(job: CatalogingJob) -> dict[str, Any]:
    operation = job.operation if job.operation_id else None
    process_metrics = (
        operation.process_metrics_json
        if operation is not None and isinstance(operation.process_metrics_json, dict)
        else {}
    )
    return {
        "id": job.id,
        "project_id": job.project_id,
        "status": job.status,
        "execution_mode": job.execution_mode,
        "execution_backend": job.execution_backend or "internal_llm",
        "agent_run_id": job.agent_run_id,
        "operation_id": job.operation_id,
        "current_chapter_id": job.current_chapter_id,
        "last_completed_chapter_id": job.last_completed_chapter_id,
        "blocked_chapter_id": job.blocked_chapter_id,
        "context_integrity": job.context_integrity,
        "total_chapters": job.total_chapters or 0,
        "completed_chapters": job.completed_chapters or 0,
        "failed_chapters": job.failed_chapters or 0,
        "model": job.model,
        "effective_model": job.model,
        "model_source": job.model_source,
        "provider": job.provider,
        "error": job.error,
        "review_warning": _job_review_warning(job),
        "current_stage": operation.phase if operation is not None else None,
        "current_message": operation.current_message if operation is not None else None,
        "process_alive": process_metrics.get("alive"),
        "heartbeat_at": utc_isoformat(operation.heartbeat_at) if operation is not None else None,
        "last_activity_at": (
            utc_isoformat(operation.last_activity_at) if operation is not None else None
        ),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def run_to_dict(run: CatalogingChapterRun) -> dict[str, Any]:
    chapter = run.chapter
    return {
        "id": run.id,
        "job_id": run.job_id,
        "chapter_id": run.chapter_id,
        "chapter_title": chapter.title if chapter else "",
        "status": run.status,
        "chapter_order": run.chapter_order,
        "chapter_version": run.chapter_version,
        "error": run.error,
        "review_warning": run.review_warning,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
