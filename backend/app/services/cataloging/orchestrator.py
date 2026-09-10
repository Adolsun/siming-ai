"""Sequential SSE orchestrator for project cataloging."""
from __future__ import annotations

from app.architecture.uow import commit_session

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

from sqlalchemy.orm import Session

from ...ai.local_cli_adapter import is_local_cli_provider
from ...core.provider_errors import provider_http_status, provider_protocol_rejected
from ...modules.model_runtime.application.execution import model_executor as LLMGateway
from ...database.models import CatalogingCandidate, CatalogingChapterRun, CatalogingJob, Chapter, Project
from ...database.session import SessionLocal
from ...database.write_coordination import DatabaseWriteLockTimeout
from ...modules.story.application.content_sync import (
    enqueue_project_sync,
    ensure_chapter_mirror,
)
from ..story_granularity import CHARACTER_PROFILE_FIELDS
from .applier import apply_candidates_for_run, candidate_to_dict
from .candidate_io import candidate_has_usable_summary
from .candidate_store import (
    recover_candidates_from_response_text,
    try_create_candidates,
)
from .candidate_retry import (
    append_incremental_candidate_retry as _append_incremental_candidate_retry,
    candidate_coverage_error as _candidate_coverage_error,
    candidate_coverage_requires_model_retry as _candidate_coverage_requires_model_retry,
    candidate_coverage_review as _candidate_coverage_review,
    candidate_issue,
    candidate_issue_summary,
    candidate_retry_reason,
)
from .candidate_validation import candidate_coverage_error_message, inspect_candidate_coverage
from .constants import (
    CATALOGING_MAX_TOKENS,
    CATALOGING_STAGE_MAX_ATTEMPTS,
    CATALOGING_TIMEOUT_SECONDS,
)
from .context import ordered_chapters
from .facts import facts_to_jsonl, parse_fact_response
from .fact_store import clear_facts_for_run, create_fact, load_facts_for_run
from .jsonl import clean_jsonl_text
from .job_control import refresh_job_progress, start_cataloging_extraction, validate_cataloging_run_source
from .model_selection import cataloging_extra_body
from .staged_prompts import (
    CATALOGING_RESOLUTION_SYSTEM_PROMPT,
    FACT_EXTRACTION_SYSTEM_PROMPT,
    build_fact_extraction_prompt,
    build_resolution_prompt,
)
from .targeted_context import build_targeted_context
from .projection import _promote_legacy_review_warning, job_to_dict, run_to_dict, sse_event


class CatalogingStopped(Exception):
    """The author changed durable control state while a provider was running."""


def _provider_rejected_request(error: BaseException) -> bool:
    status = provider_http_status(error)
    return (
        status is not None and 400 <= status < 500
        and status not in {408, 409, 425, 429}
    ) or provider_protocol_rejected(error)


def _check_active_job(db: Session, job: CatalogingJob) -> None:
    db.refresh(job)
    if job.status not in {"queued", "running"}:
        raise CatalogingStopped(job.status)


def _recover_complete_candidate_response(
    db: Session,
    job: CatalogingJob,
    run: CatalogingChapterRun,
    response_text: str,
    *,
    source_task: str,
) -> tuple[dict[str, Any], list[CatalogingCandidate]]:
    """Run whole-response recovery and commit only a complete candidate set."""

    report = recover_candidates_from_response_text(
        db,
        job,
        run,
        response_text,
        source_task=source_task,
    )
    candidates = [
        result["candidate"]
        for result in report.get("results", [])
        if result.get("candidate")
    ]
    if candidates:
        commit_session(db)
    return report, candidates


def _model_provider(model: str | None) -> str:
    try:
        provider, _ = LLMGateway.model_identity(model, {"moshu_task_type": "cataloging"})
        return provider
    except Exception:
        return (model or "").split(":", 1)[0].lower()


def _is_local_runtime_provider(provider: str) -> bool:
    return provider == "local_llama_cpp"


def _fact_prompt_messages(
    *,
    chapter_title: str,
    chapter_content: str,
    chapter_file: str,
    model: str | None,
) -> list[dict[str, str]]:
    provider = _model_provider(model)
    if chapter_file and is_local_cli_provider(provider):
        user_content = (
            f"当前章节标题：{chapter_title}\n\n"
            f"当前章节 UTF-8 镜像文件：{chapter_file}\n\n"
            "请完整读取附件中的章节正文，按系统规则输出事实 JSONL。"
            "先输出 chapter_overview，再输出角色、关系、世界观、大纲和身份线索事实。"
        )
    else:
        user_content = build_fact_extraction_prompt(
            chapter_title,
            chapter_content,
        )
    return [
        {"role": "system", "content": FACT_EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


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
    _check_active_job(db, job)
    provider = _model_provider(job.model)
    chapter = validate_cataloging_run_source(db, job, run)
    candidates = db.query(CatalogingCandidate).filter_by(chapter_run_id=run.id).all()
    if candidates and all(row.status in {"applied", "rejected"} for row in candidates) and not _candidate_coverage_error(db, run):
        run.status = "awaiting_confirmation"
        run.error = None
        commit_session(db)
        yield sse_event({"type": "chapter_extracted", "run": run_to_dict(run), "candidate_count": len(candidates)})
        return
    project_folder, chapter_file, chapter_text = _chapter_source(db, job, run, chapter)

    start_cataloging_extraction(db, job, run, chapter)
    yield sse_event({"type": "chapter_started", "job": job_to_dict(job), "run": run_to_dict(run)})

    raw_fact_parts: list[str] = []
    raw_candidate_parts: list[str] = []
    facts: list[dict[str, Any]] = []
    candidate_count = db.query(CatalogingCandidate).filter(CatalogingCandidate.chapter_run_id == run.id).count()
    has_summary = db.query(CatalogingCandidate).filter(
        CatalogingCandidate.chapter_run_id == run.id,
        CatalogingCandidate.item_type == "chapter_summary",
    ).first() is not None
    local_runtime = _is_local_runtime_provider(provider)

    try:
        facts = load_facts_for_run(db, run)
        if facts:
            yield sse_event({
                "type": "cataloging_stage",
                "message": f"第一阶段：复用已保存事实 {len(facts)} 条",
                "run": run_to_dict(run),
            })
        else:
            yield sse_event({"type": "cataloging_stage", "message": "第一阶段：裸读章节，抽取事实线索", "run": run_to_dict(run)})
            previous_fact_error = ""
            for attempt in range(1, CATALOGING_STAGE_MAX_ATTEMPTS + 1):
                attempt_fact_parts: list[str] = []
                if attempt > 1:
                    facts = []
                    raw_fact_parts.append(f"\n\n=== FACT EXTRACTION RETRY {attempt} ===\n")
                try:
                    messages = _fact_prompt_messages(
                        chapter_title=chapter.title, chapter_content=chapter_text,
                        chapter_file=chapter_file, model=job.model,
                    )
                    if previous_fact_error:
                        messages[-1]["content"] += (
                            "\n\n上次事实响应未通过校验：" + previous_fact_error
                            + "\n请修正上述结构错误，重新输出覆盖完整正文的全部事实；上次的部分结果未保存。"
                        )
                    fact_stream = LLMGateway.stream_chat_completion(
                        messages=messages,
                        model=job.model,
                        temperature=0.1,
                        max_tokens=min(CATALOGING_MAX_TOKENS, 12000),
                        timeout=CATALOGING_TIMEOUT_SECONDS,
                        retry=1,
                        extra_body=cataloging_extra_body(
                            job.model,
                            cwd=project_folder or None,
                            attachments=[chapter_file] if chapter_file and is_local_cli_provider(provider) else None,
                        ),
                    )
                    async for chunk in fact_stream:
                        _check_active_job(db, job)
                        raw_fact_parts.append(chunk)
                        attempt_fact_parts.append(chunk)
                    # Source facts are one validated checkpoint, never a set of
                    # independently reusable prefixes from an interrupted stream.
                    facts = parse_fact_response("".join(attempt_fact_parts))
                    _check_active_job(db, job)
                    for index, fact in enumerate(facts):
                        create_fact(db, job, run, fact, index)
                    run.status = "facts_saved"
                    commit_session(db)
                    for fact in facts:
                        yield sse_event({
                            "type": "fact_extracted", "fact": fact,
                            "message": f"已保存完整事实: {fact.get('fact_type')}",
                            "run": run_to_dict(run),
                        })
                    break
                except CatalogingStopped:
                    raise
                except Exception as exc:
                    db.rollback()
                    _check_active_job(db, job)
                    previous_fact_error = str(exc)[:2000]
                    clear_facts_for_run(db, run)
                    commit_session(db)
                    facts = []
                    raw_fact_parts.append(f"\n[FACT EXTRACTION FAILED: {exc}]\n")
                    if _provider_rejected_request(exc) or attempt >= CATALOGING_STAGE_MAX_ATTEMPTS:
                        raise
                    yield sse_event({
                        "type": "cataloging_retry",
                        "stage": "fact_extraction",
                        "message": f"第一阶段失败，正在自动重试 {attempt + 1}/{CATALOGING_STAGE_MAX_ATTEMPTS}",
                        "attempt": attempt + 1,
                        "max_attempts": CATALOGING_STAGE_MAX_ATTEMPTS,
                        "error": str(exc),
                        "run": run_to_dict(run),
                    })

        if not facts:
            raise ValueError("模型未输出可用事实，已暂停在当前章节")

        targeted_context = build_targeted_context(db, job.project_id, chapter, facts)
        if local_runtime:
            targeted_context = _compact_local_runtime_context(targeted_context)
        yield sse_event({
            "type": "cataloging_stage",
            "message": (
                "第二阶段：已按事实检索相关卡片，"
                f"角色 {len(targeted_context['relevant_characters'])} 个，"
                f"世界观 {len(targeted_context['relevant_worldbuilding'])} 条"
            ),
            "run": run_to_dict(run),
        })

        bad_lines: list[str] = []
        candidate_issues: list[dict[str, Any]] = []
        previous_retry_reason = (
            candidate_retry_reason(db, run, [], _candidate_coverage_error(db, run))
            if candidate_count else ""
        )
        for attempt in range(1, CATALOGING_STAGE_MAX_ATTEMPTS + 1):
            candidate_buffer = ""
            bad_lines = []
            candidate_issues = []
            attempt_parts: list[str] = []
            if attempt > 1:
                raw_candidate_parts.append(f"\n\n=== CANDIDATE RESOLUTION RETRY {attempt} ===\n")
            try:
                resolution_prompt = build_resolution_prompt(
                    facts_to_jsonl(facts),
                    json.dumps(targeted_context, ensure_ascii=False, separators=(",", ":")),
                    chapter.title,
                )
                if previous_retry_reason:
                    resolution_prompt = _append_incremental_candidate_retry(
                        resolution_prompt,
                        previous_retry_reason,
                    )
                candidate_stream = LLMGateway.stream_chat_completion(
                    messages=[
                        {"role": "system", "content": CATALOGING_RESOLUTION_SYSTEM_PROMPT},
                        {"role": "user", "content": resolution_prompt},
                    ],
                    model=job.model,
                    temperature=0.1,
                    max_tokens=CATALOGING_MAX_TOKENS,
                    timeout=CATALOGING_TIMEOUT_SECONDS,
                    retry=1,
                    extra_body=cataloging_extra_body(
                        job.model,
                        cwd=project_folder or None,
                    ),
                )
                async for chunk in candidate_stream:
                    _check_active_job(db, job)
                    raw_candidate_parts.append(chunk)
                    attempt_parts.append(chunk)
                    candidate_buffer += chunk
                    lines = candidate_buffer.splitlines(keepends=True)
                    if lines and not lines[-1].endswith(("\n", "\r")):
                        candidate_buffer = lines.pop()
                    else:
                        candidate_buffer = ""
                    for line in lines:
                        for created in try_create_candidates(db, job, run, line, candidate_count):
                            if created.get("bad_line"):
                                bad_lines.append(created["bad_line"])
                                candidate_issues.append(candidate_issue(created))
                                yield sse_event({"type": "parse_warning", "run": run_to_dict(run), "line": created["bad_line"][:500], "error": created["error"]})
                            if created.get("skipped"):
                                reason = created.get("reason") or "候选缺少有效内容，已跳过"
                                yield sse_event({
                                    "type": "candidate_skipped",
                                    "run": run_to_dict(run),
                                    "message": reason,
                                    "reason": reason,
                                })
                            candidate = created.get("candidate")
                            if candidate:
                                candidate_count += 1
                                has_summary = has_summary or candidate_has_usable_summary(candidate)
                                commit_session(db)
                                yield sse_event({"type": "candidate_created", "candidate": candidate_to_dict(candidate), "run": run_to_dict(run)})
                tail = clean_jsonl_text(candidate_buffer)
                if tail:
                    for created in try_create_candidates(db, job, run, tail, candidate_count):
                        if created.get("bad_line"):
                            bad_lines.append(created["bad_line"])
                            candidate_issues.append(candidate_issue(created))
                            yield sse_event({
                                "type": "parse_warning", "run": run_to_dict(run),
                                "line": created["bad_line"][:500], "error": created["error"],
                            })
                        if created.get("skipped"):
                            reason = created.get("reason") or "候选缺少有效内容，已跳过"
                            yield sse_event({
                                "type": "candidate_skipped",
                                "run": run_to_dict(run),
                                "message": reason,
                                "reason": reason,
                            })
                        if created.get("candidate"):
                            candidate = created["candidate"]
                            candidate_count += 1
                            has_summary = has_summary or candidate_has_usable_summary(candidate)
                            commit_session(db)
                            yield sse_event({"type": "candidate_created", "candidate": candidate_to_dict(candidate), "run": run_to_dict(run)})
                coverage_reason = _candidate_coverage_error(db, run)
                if bad_lines or coverage_reason:
                    recovery, recovered_candidates = _recover_complete_candidate_response(
                        db,
                        job,
                        run,
                        "".join(attempt_parts),
                        source_task="resolution_response_recovery",
                    )
                    for candidate in recovered_candidates:
                        candidate_count += 1
                        has_summary = has_summary or candidate_has_usable_summary(candidate)
                        yield sse_event({
                            "type": "candidate_created",
                            "candidate": candidate_to_dict(candidate),
                            "run": run_to_dict(run),
                            "recovered": True,
                        })
                    coverage_reason = _candidate_coverage_error(db, run)
                    recovered_errors = [result for result in recovery.get("results", []) if result.get("bad_line")]
                    if recovered_errors:
                        bad_lines = [result["bad_line"] for result in recovered_errors]
                        candidate_issues = [candidate_issue(result) for result in recovered_errors]
                    elif recovery["coverage"].is_complete and not coverage_reason:
                        bad_lines = []
                        candidate_issues = []

                retry_reason = (
                    candidate_issue_summary(candidate_issues)
                    if bad_lines
                    else coverage_reason
                )
                if not retry_reason:
                    break
                if not bad_lines and not _candidate_coverage_requires_model_retry(db, run):
                    break
                if attempt >= CATALOGING_STAGE_MAX_ATTEMPTS:
                    if local_runtime:
                        yield sse_event({
                            "type": "cataloging_warning",
                            "stage": "candidate_resolution",
                            "message": f"第二阶段本地模型未输出完整候选（{retry_reason}），已暂停当前章节；不会用模板生成候选。请换更强模型、外部 CLI，或重跑第二阶段。",
                            "run": run_to_dict(run),
                        })
                    break
                previous_retry_reason = candidate_retry_reason(
                    db, run, candidate_issues, coverage_reason,
                )
                yield sse_event({
                    "type": "cataloging_retry",
                    "stage": "candidate_resolution",
                    "message": f"第二阶段失败，正在自动重试 {attempt + 1}/{CATALOGING_STAGE_MAX_ATTEMPTS}",
                    "attempt": attempt + 1,
                    "max_attempts": CATALOGING_STAGE_MAX_ATTEMPTS,
                    "error": retry_reason,
                    "run": run_to_dict(run),
                })
            except CatalogingStopped:
                raise
            except Exception as exc:
                db.rollback()
                _check_active_job(db, job)
                recovery, recovered_candidates = _recover_complete_candidate_response(
                    db,
                    job,
                    run,
                    "".join(attempt_parts),
                    source_task="resolution_interrupted_response_recovery",
                )
                recovered_errors = [result for result in recovery.get("results", []) if result.get("bad_line")]
                if recovery["coverage"].is_complete and not recovered_errors:
                    for candidate in recovered_candidates:
                        candidate_count += 1
                        has_summary = has_summary or candidate_has_usable_summary(candidate)
                        yield sse_event({
                            "type": "candidate_created",
                            "candidate": candidate_to_dict(candidate),
                            "run": run_to_dict(run),
                            "recovered": True,
                        })
                    bad_lines = []
                    candidate_issues = []
                    break
                if _provider_rejected_request(exc):
                    raise
                if attempt >= CATALOGING_STAGE_MAX_ATTEMPTS and local_runtime:
                    yield sse_event({
                        "type": "cataloging_warning",
                        "stage": "candidate_resolution",
                        "message": f"第二阶段本地模型失败（{exc}），已暂停当前章节；不会用模板生成候选。请换更强模型、外部 CLI，或重跑第二阶段。",
                        "run": run_to_dict(run),
                    })
                    raise ValueError(f"第二阶段本地模型失败（{exc}），已暂停当前章节")
                if attempt >= CATALOGING_STAGE_MAX_ATTEMPTS:
                    raise
                candidate_buffer = ""
                bad_lines = []
                candidate_issues = []
                previous_retry_reason = candidate_retry_reason(
                    db, run,
                    [candidate_issue(result) for result in recovered_errors]
                    or [{"kind": "candidate_processing", "message": str(exc)}],
                    _candidate_coverage_error(db, run),
                )
                raw_candidate_parts.append(f"\n[CANDIDATE RESOLUTION FAILED: {exc}]\n")
                yield sse_event({
                    "type": "cataloging_retry",
                    "stage": "candidate_resolution",
                    "message": f"第二阶段失败，正在自动重试 {attempt + 1}/{CATALOGING_STAGE_MAX_ATTEMPTS}",
                    "attempt": attempt + 1,
                    "max_attempts": CATALOGING_STAGE_MAX_ATTEMPTS,
                    "error": str(exc),
                    "run": run_to_dict(run),
                })
    except CatalogingStopped:
        yield sse_event({"type": job.status, "job": job_to_dict(job)})
        return
    except Exception as exc:
        db.rollback()
        db.refresh(job)
        if job.status not in {"queued", "running"}:
            yield sse_event({"type": job.status, "job": job_to_dict(job)})
            return
        run.status = "failed"
        run.error = str(exc)
        run.raw_output = _combined_raw_output(raw_fact_parts, raw_candidate_parts)
        job.status = "paused_on_failure"
        job.blocked_chapter_id = run.chapter_id
        job.error = run.error
        commit_session(db)
        yield sse_event({"type": "chapter_failed", "run": run_to_dict(run), "error": run.error})
        return

    run.raw_output = _combined_raw_output(raw_fact_parts, raw_candidate_parts)
    if bad_lines:
        run.status = "failed"
        run.error = (
            candidate_issue_summary(candidate_issues, details=True)
            + "，已暂停在当前章节"
        )
        job.status = "paused_on_failure"
        job.blocked_chapter_id = run.chapter_id
        job.error = run.error
        commit_session(db)
        yield sse_event({"type": "chapter_failed", "run": run_to_dict(run), "error": run.error, "bad_lines": bad_lines[:5]})
        return
    coverage_error = _candidate_coverage_error(db, run)
    if coverage_error:
        run.status = "failed"
        run.error = f"{coverage_error}，已暂停在当前章节"
        job.status = "paused_on_failure"
        job.blocked_chapter_id = run.chapter_id
        job.error = run.error
        commit_session(db)
        yield sse_event({"type": "chapter_failed", "run": run_to_dict(run), "error": run.error})
        return

    coverage_review = _candidate_coverage_review(db, run)
    run.status = "awaiting_confirmation"
    run.completed_at = datetime.utcnow()
    run.error = None
    run.review_warning = coverage_review or None
    commit_session(db)
    yield sse_event({"type": "chapter_extracted", "run": run_to_dict(run), "candidate_count": candidate_count})


def _combined_raw_output(raw_fact_parts: list[str], raw_candidate_parts: list[str]) -> str:
    value = (
        "=== FACT EXTRACTION ===\n"
        + "".join(raw_fact_parts)
        + "\n\n=== CANDIDATE RESOLUTION ===\n"
        + "".join(raw_candidate_parts)
    )
    return value[-60000:]


def _compact_local_runtime_context(context: dict[str, Any]) -> dict[str, Any]:
    """Keep staged resolution prompts small enough for managed local models."""
    def aliases(value: Any, limit: int = 6) -> list[Any]:
        if not isinstance(value, list):
            return []
        compacted = []
        for item in value[:limit]:
            if isinstance(item, dict):
                compacted.append({
                    "alias": _clip_local_context(item.get("alias"), 80),
                    "alias_type": _clip_local_context(item.get("alias_type"), 40),
                })
            else:
                compacted.append(_clip_local_context(item, 80))
        return [item for item in compacted if item]

    def character(item: dict[str, Any]) -> dict[str, Any]:
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        ai_style = item.get("ai_style") if isinstance(item.get("ai_style"), dict) else {}
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "aliases": aliases(item.get("aliases")),
            "role_type": item.get("role_type"),
            "age": item.get("age"),
            "appearance": item.get("appearance"),
            "personality": _clip_local_context(item.get("personality"), 180),
            "background": item.get("background"),
            "abilities": (item.get("abilities") or [])[:8] if isinstance(item.get("abilities"), list) else [],
            "life_status": item.get("life_status"),
            "current_location": _clip_local_context(item.get("current_location"), 120),
            "realm_or_level": _clip_local_context(item.get("realm_or_level"), 120),
            "physical_state": _clip_local_context(item.get("physical_state"), 140),
            "mental_state": _clip_local_context(item.get("mental_state"), 140),
            "current_goal": _clip_local_context(item.get("current_goal"), 160),
            "active_conflict": _clip_local_context(item.get("active_conflict"), 160),
            "abilities_state": _clip_local_context(item.get("abilities_state"), 160),
            "items_or_assets": item.get("items_or_assets"),
            # Stable writing locks and speech style are continuity data too.
            # Dropping them only for local runtimes made the CLI route unable
            # to distinguish an already-complete card from a missing field.
            "profile": {
                key: _clip_local_context(profile.get(key), 220)
                for key in CHARACTER_PROFILE_FIELDS
                if profile.get(key) not in (None, "", [], {})
            },
            "ai_style": {
                "tone_style": _clip_local_context(ai_style.get("tone_style"), 100),
                "catchphrases": (
                    ai_style.get("catchphrases", [])[:6]
                    if isinstance(ai_style.get("catchphrases"), list)
                    else []
                ),
                "verbosity": _clip_local_context(ai_style.get("verbosity"), 50),
                "emotion_tendency": _clip_local_context(ai_style.get("emotion_tendency"), 100),
                "custom_system_prompt": _clip_local_context(ai_style.get("custom_system_prompt"), 500),
            },
            "recent_timeline": [
                {
                    "event_type": event.get("event_type"),
                    "event_description": _clip_local_context(event.get("event_description"), 140),
                }
                for event in (item.get("recent_timeline") or [])[:2]
                if isinstance(event, dict)
            ],
        }

    def worldbuilding(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id"),
            "dimension": item.get("dimension"),
            "title": item.get("title"),
            "status": item.get("status"),
            "content": _clip_local_context(item.get("content"), 320),
            "recent_timeline": [
                {
                    "event_type": event.get("event_type"),
                    "event_description": _clip_local_context(event.get("event_description"), 140),
                }
                for event in (item.get("recent_timeline") or [])[:2]
                if isinstance(event, dict)
            ],
        }

    lookup_terms = context.get("lookup_terms") or {}
    return {
        "current_chapter": context.get("current_chapter"),
        "recent_chapter_summaries": [
            {
                "title": item.get("title"),
                "summary": _clip_local_context(item.get("summary"), 280),
                "key_events": (item.get("key_events") or [])[:4] if isinstance(item.get("key_events"), list) else [],
            }
            for item in (context.get("recent_chapter_summaries") or [])[-4:]
            if isinstance(item, dict)
        ],
        "character_name_index": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "age": item.get("age"),
                "role_type": item.get("role_type"),
                "life_status": item.get("life_status"),
                "aliases": aliases(item.get("aliases"), 4),
            }
            for item in (context.get("character_name_index") or [])[:80]
            if isinstance(item, dict)
        ],
        "relevant_characters": [
            character(item)
            for item in (context.get("relevant_characters") or [])
            if isinstance(item, dict)
        ],
        "relevant_relationships": [
            {
                "source_name": item.get("source_name"),
                "target_name": item.get("target_name"),
                "relationship_type": item.get("relationship_type"),
                "description": _clip_local_context(item.get("description"), 140),
            }
            for item in (context.get("relevant_relationships") or [])[:16]
            if isinstance(item, dict)
        ],
        "worldbuilding_title_index": [
            {
                "id": item.get("id"),
                "dimension": item.get("dimension"),
                "title": item.get("title"),
            }
            for item in (context.get("worldbuilding_title_index") or [])[:100]
            if isinstance(item, dict)
        ],
        "worldbuilding_identity_review_required": context.get(
            "worldbuilding_identity_review_required", [],
        ),
        "relevant_worldbuilding": [
            worldbuilding(item)
            for item in (context.get("relevant_worldbuilding") or [])
            if isinstance(item, dict)
        ],
        "nearby_outline_nodes": [
            {
                "title": item.get("title"),
                "node_type": item.get("node_type"),
                "summary": _clip_local_context(item.get("summary"), 180),
                "actual_summary": _clip_local_context(item.get("actual_summary"), 180),
                "planned_summary": _clip_local_context(item.get("planned_summary"), 180),
            }
            for item in (context.get("nearby_outline_nodes") or [])[:18]
            if isinstance(item, dict)
        ],
        "lookup_terms": {
            "names": lookup_terms.get("names", [])[:40],
            "titles": lookup_terms.get("titles", [])[:40],
            "keywords": lookup_terms.get("keywords", [])[:40],
        },
    }


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
    if not applied_coverage.is_complete:
        run.status = "failed"
        run.error = candidate_coverage_error_message(
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


def _chapter_source(
    db: Session, job: CatalogingJob, run: CatalogingChapterRun, chapter: Chapter,
) -> tuple[str, str, str]:
    project = db.query(Project).filter(Project.id == job.project_id).first()
    project_folder = ""
    chapter_file = ""
    if project:
        folder, path = ensure_chapter_mirror(db, project, chapter, index=run.chapter_order + 1, source="cataloging")
        project_folder = str(folder)
        chapter_file = str(path)
    chapter_text = chapter.content or ""
    if not chapter_text and chapter_file:
        try:
            chapter_text = Path(chapter_file).read_text(encoding="utf-8")
        except Exception:
            chapter_text = ""
    return project_folder, chapter_file, chapter_text


def _clip_local_context(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:limit]
