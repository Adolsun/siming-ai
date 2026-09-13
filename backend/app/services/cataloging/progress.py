"""Read-only cataloging progress for desktop, mobile, and CLI observers."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy.orm import Session

from ...architecture.uow import commit_session
from ...database.models import (
    AgentRunEvent,
    CatalogingCandidate,
    CatalogingChapterRun,
    CatalogingFact,
    CatalogingJob,
    OperationEvent,
)
from ...database.session import SessionLocal
from ..operation_runtime import add_operation_event
from .candidate_io import candidate_to_dict
from .fact_store import fact_to_dict
from .job_control import TERMINAL_RUN_STATUSES
from .projection import job_to_dict, run_to_dict, sse_event

POLL_SECONDS = 0.5
_PROGRESS_EVENT = "cataloging_progress"
_DETAIL_TYPES = {
    "cataloging_stage",
    "cataloging_tool_result",
    "cataloging_retry",
    "cataloging_warning",
    "parse_warning",
    "fact_parse_warning",
    "candidate_skipped",
}


def record_cataloging_progress(db: Session, job: CatalogingJob, raw: str) -> None:
    """The worker records diagnostics in its own transaction, never an observer.

    Entity state remains in the cataloging tables. Only transient stage/retry
    details use the existing operation log; replay must not overwrite current
    job/run snapshots with historical state.
    """
    if not job.operation_id or not raw.startswith("data: {"):
        return
    event = json.loads(raw.removeprefix("data: "))
    if event.get("type") not in _DETAIL_TYPES:
        return
    operation = job.operation
    if operation is None:
        return
    if event.get("stage") == "planning":
        operation.phase = "planning"
    payload = {key: value for key, value in event.items() if key not in {"run", "job"}}
    if event.get("run"):
        payload["chapter_run_id"] = event["run"]["id"]
    add_operation_event(db, operation, _PROGRESS_EVENT, job.status, event.get("message"), payload)
    commit_session(db)


async def observe_cataloging_job(project_id: str, job_id: str):
    """Observe committed state only; reconnecting never starts or resumes work."""

    seen_runs: dict[str, dict[str, Any]] = {}
    seen_facts: dict[str, dict[str, Any]] = {}
    seen_candidates: dict[str, dict[str, Any]] = {}
    last_job: dict[str, Any] | None = None
    last_agent_id: str | None = None
    last_agent_sequence = 0
    last_progress_sequence = 0
    first = True

    while True:
        # Release the read transaction and connection before waiting or yielding
        # to a slow/disconnected client. SQLite writers must remain independent.
        events: list[dict[str, Any]] = []
        done = False
        with SessionLocal() as db:
            job = db.query(CatalogingJob).filter_by(id=job_id, project_id=project_id).first()
            if job is None:
                events.append({"type": "error", "message": "作品建档任务不存在或已被删除"})
                done = True
            else:
                job_data = job_to_dict(job)
                runs = (
                    db.query(CatalogingChapterRun)
                    .filter_by(job_id=job_id)
                    .order_by(CatalogingChapterRun.chapter_order.asc())
                    .all()
                )
                if first:
                    events.append(
                        {
                            "type": "cataloging_stage",
                            "job": job_data,
                            "message": "建档进度已加载；此连接只观察任务，不会重复启动建档",
                        }
                    )
                    # Historical diagnostics are available in the operation log.
                    # Start live replay at the current cursor, avoiding old errors
                    # from a previous retry of this same job.
                    latest = (
                        db.query(OperationEvent.sequence)
                        .filter_by(run_id=job.operation_id, event_type=_PROGRESS_EVENT)
                        .order_by(OperationEvent.sequence.desc())
                        .first()
                    )
                    last_progress_sequence = latest[0] if latest else 0
                events.extend(_chapter_progress_events(
                    db, job, runs, job_data, seen_runs, seen_facts, seen_candidates,
                ))
                if job.agent_run_id != last_agent_id:
                    last_agent_id = job.agent_run_id
                    last_agent_sequence = 0
                if last_agent_id:
                    agent_events = (
                        db.query(AgentRunEvent)
                        .filter(
                            AgentRunEvent.run_id == last_agent_id,
                            AgentRunEvent.sequence > last_agent_sequence,
                        )
                        .order_by(AgentRunEvent.sequence.asc())
                        .all()
                    )
                    for event in agent_events:
                        last_agent_sequence = event.sequence
                        events.append(
                            {
                                "type": "agent_event",
                                "message": event.message or event.event_type,
                                "agent_event": {
                                    "sequence": event.sequence,
                                    "event_type": event.event_type,
                                    "status": event.status,
                                    "payload_json": event.payload_json,
                                },
                                "job": job_data,
                            }
                        )
                if job.operation_id:
                    progress_events = (
                        db.query(OperationEvent)
                        .filter(
                            OperationEvent.run_id == job.operation_id,
                            OperationEvent.event_type == _PROGRESS_EVENT,
                            OperationEvent.sequence > last_progress_sequence,
                        )
                        .order_by(OperationEvent.sequence.asc())
                        .all()
                    )
                    for event in progress_events:
                        last_progress_sequence = event.sequence
                        events.append(dict(event.payload_json or {}))
                if job_data != last_job:
                    last_job = job_data
                    events.append({"type": "job", "job": job_data})
                done = job.status in {
                    "completed",
                    "paused_on_failure",
                    "paused",
                    "cancelled",
                    "failed",
                }
                done = done or (
                    job.status == "waiting_confirmation" and job.execution_mode == "manual"
                )
                if done:
                    blocking = next(
                        (run for run in runs if run.chapter_id == job.blocked_chapter_id), None
                    )
                    events.append(
                        {
                            "type": job.status,
                            "job": job_data,
                            "run": run_to_dict(blocking) if blocking else None,
                            "error": job.error,
                        }
                    )
        for event in events:
            yield sse_event(event)
        if done:
            yield "data: [DONE]\n\n"
            return
        first = False
        await asyncio.sleep(POLL_SECONDS)


def _chapter_progress_events(
    db: Session, job: CatalogingJob, runs: list[CatalogingChapterRun],
    job_data: dict[str, Any], seen_runs: dict[str, dict[str, Any]],
    seen_facts: dict[str, dict[str, Any]], seen_candidates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    job_id = job.id
    for run in runs:
        data = run_to_dict(run)
        if seen_runs.get(run.id) == data:
            continue
        previous_status = (seen_runs.get(run.id) or {}).get("status")
        seen_runs[run.id] = data
        event_type = "chapter_state"
        if previous_status != run.status:
            if run.status in {"in_progress", "extracting"}:
                event_type = "chapter_started"
            elif run.status in TERMINAL_RUN_STATUSES:
                event_type = "chapter_completed"
            elif run.status == "failed":
                event_type = "chapter_failed"
            elif run.status == "applying":
                event_type = "chapter_applying"
            elif run.status == "awaiting_confirmation":
                event_type = "chapter_extracted"
        events.append(
            {
                "type": event_type,
                "job": job_data,
                "run": data,
                "message": f"第 {run.chapter_order + 1} 章：{run.status}",
            }
        )

    # Replay the current chapter's durable records on first connect
    # as well as reconnect. IDs let clients upsert, never duplicate.
    current_chapter = (
        job.blocked_chapter_id
        or job.current_chapter_id
        or job.last_completed_chapter_id
    )
    if current_chapter:
        for model, seen, serialize, kind, field in (
            (CatalogingFact, seen_facts, fact_to_dict, "fact_extracted", "fact"),
            (
                CatalogingCandidate,
                seen_candidates,
                candidate_to_dict,
                "candidate_created",
                "candidate",
            ),
        ):
            rows = (
                db.query(model)
                .filter_by(job_id=job_id, chapter_id=current_chapter)
                .order_by(model.created_at.asc(), model.id.asc())
                .all()
            )
            for row in rows:
                data = serialize(row)
                if seen.get(row.id) == data:
                    continue
                seen[row.id] = data
                events.append(
                    {
                        "type": kind,
                        field: data,
                        "job": job_data,
                        "run": run_to_dict(row.chapter_run),
                    }
                )

    return events
