"""Create and launch the canonical cataloging pipeline.

Chapter writes, the cataloging UI, and workspace tools all enter cataloging
through this module.  Keeping launch policy here prevents a second post-write
candidate generator from drifting away from the main cataloging workflow.
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.orm import Session

from ...ai.local_cli_adapter import DEFAULT_CLI_MODELS, is_local_cli_provider
from ...architecture.uow import commit_session
from ...database.models import (
    APIConfig,
    AgentRun,
    CatalogingChapterRun,
    CatalogingJob,
    Chapter,
    OperationRun,
)
from ...database.session import SessionLocal
from .job_control import cancel_job, refresh_job_progress
from .local_cli_agent import (
    cancel_local_cli_cataloging_worker,
    ensure_local_cli_cataloging_worker,
)
from .model_selection import cataloging_model_selection
from .orchestrator import create_cataloging_job, job_to_dict, stream_cataloging_job


AUTO_CHAPTER_WRITE_SOURCE = "chapter_write"
_LAUNCH_TASKS: dict[str, asyncio.Task[None]] = {}
_TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


def _configured_cli_model(db: Session, provider: str) -> str | None:
    config = (
        db.query(APIConfig)
        .filter(
            APIConfig.provider_type == "local_cli",
            APIConfig.provider == provider,
        )
        .first()
    )
    if not config:
        return None
    model = config.default_model or DEFAULT_CLI_MODELS.get(provider, provider)
    return f"{provider}:{model}"


def resolve_write_cataloging_route(
    db: Session,
    args: dict[str, Any],
    *,
    project_id: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Return ``(model_override, backend_override, provider_override)``.

    Internal writes keep the model selected by the writer.  A managed local
    CLI write resolves its provider from the trusted AgentRun marker injected
    by the MCP adapter.  An unmanaged MCP client gets an external-agent job and
    never silently spends the user's internal API credits.
    """

    explicit_model = str(
        args.get("_cataloging_model")
        or args.get("cataloging_model")
        or args.get("model")
        or ""
    ).strip() or None
    execution_route = str(args.get("_context_execution_route") or "").strip()
    agent_run_id = str(args.get("_source_agent_run_id") or "").strip()
    if execution_route not in {"external_mcp", "local_cli_agent"}:
        return explicit_model, None, None

    provider = ""
    if agent_run_id:
        run = (
            db.query(AgentRun)
            .filter(
                AgentRun.id == agent_run_id,
                AgentRun.source == "internal_cli",
                *([AgentRun.project_id == project_id] if project_id else []),
            )
            .first()
        )
        provider = str(getattr(run, "client_name", "") or "").strip().lower()
    if provider:
        cli_model = _configured_cli_model(db, provider)
        if cli_model:
            return cli_model, "local_cli_agent", provider
    return None, "external_agent", provider or None


def _cancel_superseded_write_jobs(
    db: Session,
    project_id: str,
    chapter_ids: list[str],
) -> list[str]:
    if not chapter_ids:
        return []
    jobs = (
        db.query(CatalogingJob)
        .join(CatalogingChapterRun, CatalogingChapterRun.job_id == CatalogingJob.id)
        .filter(
            CatalogingJob.project_id == project_id,
            CatalogingJob.model_source.like(f"{AUTO_CHAPTER_WRITE_SOURCE}:%"),
            CatalogingJob.status.notin_(_TERMINAL_JOB_STATUSES),
            CatalogingChapterRun.chapter_id.in_(chapter_ids),
        )
        .distinct()
        .all()
    )
    cancelled: list[str] = []
    for job in jobs:
        cancel_job(job)
        refresh_job_progress(db, job)
        if job.execution_backend == "local_cli_agent":
            cancel_local_cli_cataloging_worker(job.id, terminal=True)
        cancelled.append(job.id)
    if cancelled:
        commit_session(db)
    return cancelled


def create_and_queue_cataloging_job(
    db: Session,
    project_id: str,
    chapter_ids: list[str],
    *,
    execution_mode: str = "auto",
    model_override: str | None = None,
    backend_override: str | None = None,
    provider_override: str | None = None,
    trigger_source: str = "manual",
    run_now: bool = True,
) -> tuple[CatalogingJob, dict[str, Any]]:
    """Create one canonical job and optionally schedule its worker."""

    backend = str(backend_override or "").strip()
    if backend == "external_agent" and not model_override:
        # An unmanaged MCP client must not cause an implicit internal-model
        # selection (or spend).  The durable job is handed back to that same
        # client through the canonical external-cataloging protocol.
        model = None
        provider = str(provider_override or "external_agent").strip().lower()
        selection_source = "external_agent"
    else:
        selection = cataloging_model_selection(model_override)
        model = selection.model
        provider = str(
            provider_override
            or selection.provider
            or (model or "").split(":", 1)[0]
            or ""
        ).strip().lower()
        selection_source = str(selection.source or "default").strip()
    if not backend:
        backend = "local_cli_agent" if is_local_cli_provider(provider) else "internal_llm"

    cancelled = (
        _cancel_superseded_write_jobs(db, project_id, chapter_ids)
        if trigger_source == AUTO_CHAPTER_WRITE_SOURCE
        else []
    )
    model_source = f"{trigger_source}:{selection_source}"[:50]
    job = create_cataloging_job(
        db,
        project_id,
        execution_mode,
        model,
        chapter_ids,
        execution_backend=backend,
        model_source=model_source,
        provider=provider or None,
    )
    if trigger_source == AUTO_CHAPTER_WRITE_SOURCE and job.operation_id:
        operation = (
            db.query(OperationRun)
            .filter(OperationRun.id == job.operation_id)
            .first()
        )
        chapters = (
            db.query(Chapter)
            .filter(
                Chapter.project_id == project_id,
                Chapter.id.in_(chapter_ids),
            )
            .all()
        )
        chapter_titles = [str(chapter.title or "未命名章节").strip() for chapter in chapters]
        chapter_label = (
            f"《{chapter_titles[0]}》"
            if len(chapter_titles) == 1
            else f"{len(chapter_titles)} 个章节"
        )
        if operation:
            operation.title = f"{chapter_label}自动建档"[:300]
            operation.tool_mode = f"auto_chapter_write:{backend}"[:80]
            operation.current_message = (
                f"{chapter_label}已保存，正在自动建档。"
                "立即生成下一章可能影响上下文质量，请耐心等待建档完成。"
            )
            commit_session(db)
    queued = False
    if run_now and backend != "external_agent":
        queue_cataloging_job(job.id)
        queued = True
    data = job_to_dict(job)
    data.update({
        "auto_started": run_now,
        "worker_queued": queued,
        "trigger_source": trigger_source,
        "superseded_job_ids": cancelled,
        "next_action": (
            "background_cataloging"
            if queued
            else "continue_external_cataloging"
        ),
    })
    return job, data


async def run_cataloging_job(job_id: str) -> None:
    """Start the worker appropriate for a previously committed job."""

    db = SessionLocal()
    try:
        job = db.query(CatalogingJob).filter(CatalogingJob.id == job_id).first()
        if not job or job.status in _TERMINAL_JOB_STATUSES:
            return
        if job.execution_backend == "local_cli_agent":
            ensure_local_cli_cataloging_worker(db, job, provider=job.provider)
            return
        if job.execution_backend == "external_agent":
            return
        project_id = job.project_id
    except Exception as exc:
        job = db.query(CatalogingJob).filter(CatalogingJob.id == job_id).first()
        if job and job.status not in _TERMINAL_JOB_STATUSES:
            job.status = "paused_on_failure"
            job.error = f"自动建档启动失败：{exc}"[:2000]
            refresh_job_progress(db, job)
            commit_session(db)
        return
    finally:
        db.close()

    try:
        async for _event in stream_cataloging_job(project_id, job_id):
            pass
    except Exception:
        # The canonical stream records its own chapter/job failure state.  The
        # durable job remains visible and retryable from the task list.
        return


def queue_cataloging_job(job_id: str) -> asyncio.Task[None]:
    existing = _LAUNCH_TASKS.get(job_id)
    if existing and not existing.done():
        return existing
    task = asyncio.create_task(
        run_cataloging_job(job_id),
        name=f"cataloging-launch-{job_id}",
    )
    _LAUNCH_TASKS[job_id] = task
    task.add_done_callback(lambda _task: _LAUNCH_TASKS.pop(job_id, None))
    return task


__all__ = [
    "AUTO_CHAPTER_WRITE_SOURCE",
    "create_and_queue_cataloging_job",
    "queue_cataloging_job",
    "resolve_write_cataloging_route",
    "run_cataloging_job",
]
