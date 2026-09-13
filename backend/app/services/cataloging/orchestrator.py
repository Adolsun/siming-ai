"""Sequential SSE orchestrator for project cataloging."""
from __future__ import annotations

from app.architecture.uow import commit_session

import asyncio
from datetime import datetime
from typing import Any, AsyncGenerator

from sqlalchemy.orm import Session

from ...modules.model_runtime.application.execution import model_executor as LLMGateway
from ...database.models import CatalogingCandidate, CatalogingChapterRun, CatalogingJob
from ...database.session import SessionLocal
from ...database.write_coordination import DatabaseWriteLockTimeout
from ...modules.story.application.content_sync import (
    enqueue_project_sync,
)
from .applier import apply_candidates_for_run
from .candidate_validation import candidate_coverage_error_message, inspect_candidate_coverage
from .constants import (
    CATALOGING_STAGE_MAX_ATTEMPTS,
)
from .context import ordered_chapters
from .job_control import refresh_job_progress, start_cataloging_extraction, validate_cataloging_run_source
from .projection import _promote_legacy_review_warning, job_to_dict, run_to_dict, sse_event


class CatalogingStopped(Exception):
    """The author changed durable control state while a provider was running."""


def _check_active_job(db: Session, job: CatalogingJob) -> None:
    db.refresh(job)
    if job.status not in {"queued", "running"}:
        raise CatalogingStopped(job.status)


def _model_provider(model: str | None) -> str:
    try:
        provider, _ = LLMGateway.model_identity(model, {"moshu_task_type": "cataloging"})
        return provider
    except Exception:
        return (model or "").split(":", 1)[0].lower()


def create_cataloging_job(
    db: Session,
    project_id: str,
    execution_mode: str,
    model: str | None,
    chapter_ids: list[str] | None,
    execution_backend: str = "internal_llm",
    model_source: str | None = None,
    provider: str | None = None,
) -> CatalogingJob:
    from ..operation_runtime import ensure_operation

    chapters = ordered_chapters(db, project_id, chapter_ids)
    job = CatalogingJob(
        project_id=project_id,
        status="queued",
        execution_mode=execution_mode if execution_mode in {"auto", "manual"} else "auto",
        execution_backend=execution_backend,
        total_chapters=len(chapters),
        completed_chapters=0,
        failed_chapters=0,
        model=model,
        model_source=model_source,
        provider=provider,
    )
    db.add(job)
    db.flush()
    operation = ensure_operation(
        db,
        source_kind="cataloging",
        source_id=job.id,
        project_id=project_id,
        title=f"作品建档 · {len(chapters)} 章",
        status="queued",
        phase="queued",
        message="建档任务已创建，正在准备第一章",
        model_source=model,
        tool_mode=execution_backend,
        resume_url=f"/project/{project_id}?view=cataloging&job={job.id}",
        can_pause=True,
        can_cancel=True,
        can_retry=True,
        progress_mode="determinate",
        progress_current=0,
        progress_total=len(chapters),
    )
    job.operation_id = operation.id
    for index, chapter in enumerate(chapters):
        db.add(CatalogingChapterRun(
            job_id=job.id,
            project_id=project_id,
            chapter_id=chapter.id,
            chapter_version=chapter.current_version or 1,
            status="pending",
            chapter_order=index,
        ))
    commit_session(db)
    db.refresh(job)
    return job


async def stream_cataloging_job(project_id: str, job_id: str) -> AsyncGenerator[str, None]:
    from ..operation_runtime import heartbeat_loop, iterate_with_operation
    from .job_control import complete_cataloging_job
    from .progress import record_cataloging_progress

    db = SessionLocal()
    heartbeat_task: asyncio.Task | None = None
    operation_id: str | None = None
    try:
        initial_job = _get_job(db, project_id, job_id)
        operation_id = initial_job.operation_id
        if operation_id:
            heartbeat_task = asyncio.create_task(heartbeat_loop(operation_id))
        yield sse_event({"type": "status", "message": "作品建档任务开始", "job_id": job_id})
        while True:
            job = _get_job(db, project_id, job_id)
            if job.status in {"completed", "failed", "cancelled", "paused", "paused_on_failure"}:
                refresh_job_progress(db, job)
                commit_session(db)
                yield sse_event({"type": "job", "job": job_to_dict(job)})
                yield "data: [DONE]\n\n"
                return

            run = _next_actionable_run(db, job)
            if not run:
                complete_cataloging_job(db, job)
                commit_session(db)
                yield sse_event({"type": "completed", "job": job_to_dict(job)})
                yield "data: [DONE]\n\n"
                return

            if run.status == "awaiting_confirmation":
                db.refresh(job)
                _promote_legacy_review_warning(run)
                if job.execution_mode != "auto":
                    job.status = "waiting_confirmation"
                    job.blocked_chapter_id = run.chapter_id
                    job.error = None
                    refresh_job_progress(db, job)
                    commit_session(db)
                    yield sse_event({"type": "waiting_confirmation", "job": job_to_dict(job), "run": run_to_dict(run)})
                    yield "data: [DONE]\n\n"
                    return
                async for event in iterate_with_operation(operation_id, _apply_run(db, job, run)):
                    record_cataloging_progress(db, job, event)
                    yield event
                continue

            if run.status == "failed":
                job.status = "paused_on_failure"
                job.blocked_chapter_id = run.chapter_id
                job.error = run.error
                refresh_job_progress(db, job)
                commit_session(db)
                yield sse_event({"type": "paused_on_failure", "job": job_to_dict(job), "run": run_to_dict(run), "error": run.error})
                yield "data: [DONE]\n\n"
                return

            async for event in iterate_with_operation(operation_id, _extract_run(db, job, run)):
                record_cataloging_progress(db, job, event)
                yield event

            db.refresh(job)
            db.refresh(run)
            _promote_legacy_review_warning(run)
            if job.status in {"cancelled", "paused"}:
                yield sse_event({"type": job.status, "job": job_to_dict(job), "run": run_to_dict(run)})
                yield "data: [DONE]\n\n"
                return
            if run.status == "failed":
                continue
            if run.status == "awaiting_confirmation" and job.execution_mode != "auto":
                run.status = "awaiting_confirmation"
                job.status = "waiting_confirmation"
                job.blocked_chapter_id = run.chapter_id
                job.error = None
                refresh_job_progress(db, job)
                commit_session(db)
                yield sse_event({"type": "waiting_confirmation", "job": job_to_dict(job), "run": run_to_dict(run)})
                yield "data: [DONE]\n\n"
                return

            async for event in iterate_with_operation(operation_id, _apply_run(db, job, run)):
                record_cataloging_progress(db, job, event)
                yield event
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        db.close()


async def _extract_run(db: Session, job: CatalogingJob, run: CatalogingChapterRun) -> AsyncGenerator[str, None]:
    from .agent import run_cataloging_agent

    _check_active_job(db, job)
    chapter = validate_cataloging_run_source(db, job, run)
    start_cataloging_extraction(db, job, run, chapter)
    yield sse_event({"type": "chapter_started", "job": job_to_dict(job), "run": run_to_dict(run)})
    yield sse_event({"type": "cataloging_stage", "stage": "planning", "message": "读取正文与档案，生成本章统一建档计划", "run": run_to_dict(run)})
    try:
        async for event in run_cataloging_agent(db, job, run, check_active=_check_active_job, gateway=LLMGateway):
            yield sse_event({**event, "run": run_to_dict(run)})
        # The shared submission boundary has validated and finalized the plan.
        db.refresh(run)
        if run.status != "awaiting_confirmation":
            raise ValueError("建档计划尚未完成校验")
        job.status = "running"
        run.error = None
        commit_session(db)
        count = db.query(CatalogingCandidate).filter_by(chapter_run_id=run.id).count()
        yield sse_event({"type": "chapter_extracted", "run": run_to_dict(run), "candidate_count": count})
    except CatalogingStopped:
        db.rollback()
        return
    except Exception as exc:
        db.rollback()
        _check_active_job(db, job)
        run.status = "failed"
        run.error = str(exc)
        job.status = "paused_on_failure"
        job.error = run.error
        job.blocked_chapter_id = run.chapter_id
        commit_session(db)
        yield sse_event({"type": "chapter_failed", "job": job_to_dict(job), "run": run_to_dict(run), "error": run.error})


async def _apply_run(db: Session, job: CatalogingJob, run: CatalogingChapterRun) -> AsyncGenerator[str, None]:
    _check_active_job(db, job)
    job_id = job.id
    run_id = run.id
    run.status = "applying"
    job.status = "running"
    commit_session(db)
    yield sse_event({"type": "chapter_applying", "job": job_to_dict(job), "run": run_to_dict(run)})
    events: list[dict[str, Any]] = []
    for attempt in range(1, CATALOGING_STAGE_MAX_ATTEMPTS + 1):
        try:
            _check_active_job(db, job)
            events = apply_candidates_for_run(db, job, run)
            break
        except DatabaseWriteLockTimeout:
            db.rollback()
            if attempt >= CATALOGING_STAGE_MAX_ATTEMPTS:
                raise
            # Never hold a transaction while backing off. Reload the durable
            # job/run before replaying the idempotent, uncommitted apply batch.
            yield sse_event({
                "type": "chapter_apply_retry",
                "job_id": job_id,
                "chapter_run_id": run_id,
                "attempt": attempt + 1,
                "reason": "database_write_lock_timeout",
            })
            await asyncio.sleep(0.25 * (2 ** (attempt - 1)))
            job = db.query(CatalogingJob).filter(CatalogingJob.id == job_id).one()
            run = db.query(CatalogingChapterRun).filter(CatalogingChapterRun.id == run_id).one()
    has_failed = any(event["type"] == "candidate_apply_failed" for event in events)
    for event in events:
        commit_session(db)
        yield sse_event(event)
    applied_candidates = (
        db.query(CatalogingCandidate)
        .filter(
            CatalogingCandidate.chapter_run_id == run.id,
            CatalogingCandidate.status == "applied",
        )
        .all()
    )
    applied_coverage = inspect_candidate_coverage(
        applied_candidates,
        db=db,
        project_id=run.project_id,
    )
    if has_failed or not applied_coverage.is_complete:
        run.status = "failed"
        run.error = next((event["error"] for event in events if event.get("type") == "candidate_apply_failed"), None) or candidate_coverage_error_message(
            applied_coverage,
            prefix="关键候选未完成写入",
        )
        job.status = "paused_on_failure"
        job.blocked_chapter_id = run.chapter_id
        job.error = run.error
        refresh_job_progress(db, job)
        commit_session(db)
        yield sse_event({
            "type": "chapter_failed",
            "job": job_to_dict(job),
            "run": run_to_dict(run),
            "error": run.error,
        })
        return
    has_warnings = has_failed or bool(run.review_warning)
    run.status = "completed_with_warnings" if has_warnings else "completed"
    run.completed_at = datetime.utcnow()
    job.last_completed_chapter_id = run.chapter_id
    job.current_chapter_id = None
    job.blocked_chapter_id = None
    job.error = None
    refresh_job_progress(db, job)
    enqueue_project_sync(db, job.project_id, source="cataloging")
    commit_session(db)
    yield sse_event({
        "type": "chapter_completed",
        "job": job_to_dict(job),
        "run": run_to_dict(run),
        "warnings": has_warnings,
        "review_warning": run.review_warning,
    })


def _next_actionable_run(db: Session, job: CatalogingJob) -> CatalogingChapterRun | None:
    return (
        db.query(CatalogingChapterRun)
        .filter(CatalogingChapterRun.job_id == job.id)
        .filter(CatalogingChapterRun.status.notin_(["completed", "completed_with_warnings", "skipped_by_user"]))
        .order_by(CatalogingChapterRun.chapter_order.asc())
        .first()
    )


def _get_job(db: Session, project_id: str, job_id: str) -> CatalogingJob:
    job = db.query(CatalogingJob).filter(CatalogingJob.id == job_id, CatalogingJob.project_id == project_id).first()
    if not job:
        raise ValueError("作品建档任务不存在")
    return job
