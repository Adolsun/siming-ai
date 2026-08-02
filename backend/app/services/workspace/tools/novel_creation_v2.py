"""Workspace tools for the resumable V2 novel creation workbench."""
from __future__ import annotations

from app.architecture.uow import commit_session

import asyncio
import json
import re
import time
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ....modules.model_runtime.application.execution import model_executor as LLMGateway
from ...operation_runtime import current_operation_id, record_operation_signal
from ....core.json_repair import parse_json_object_detailed
from ....database.models import NovelCreationMaterialImport, NovelCreationSession, NovelCreationStageRun, OperationRun
from ....services.context_orchestrator import ContextOrchestrator, activate_context_manifest
from ....services.novel_creation_authoring import (
    AuthorLockViolation,
    _WORLD_STYLE_TEXT_FIELDS,
    _author_context,
    _author_text,
    _dedupe_dicts,
    _dict_rows,
    _looks_like_cli_metadata,
    _safe_compact_concepts,
    _stage_contract,
    _validate_author_requirements,
    _validate_compact_concepts,
    _validate_stage,
)
from ....services.novel_creation_stage_runtime import stage_data_with_fallback, stage_tool_result
from ....services.novel_creation_imports import (
    apply_material_import,
    create_material_import,
    run_material_import,
    serialize_material_import,
)
from ....services.novel_creation_entities import (
    get_creation_entity as get_creation_entity_record,
    list_creation_entities as list_creation_entity_records,
    serialize_creation_entity,
)
from ....services.novel_creation_actions import (
    delete_creation_entity as delete_creation_entity_record,
    patch_creation_entity as patch_creation_entity_record,
    restore_artifact_version as restore_creation_artifact_version_record,
)
from ....services.novel_creation_consistency import (
    creation_dependency_graph,
    validate_creation_consistency,
)
from ....services.novel_creation_submission import submit_creation_stage
from ....services.novel_creation_versions import (
    artifact_version_diff,
    get_artifact_version,
    list_artifact_versions,
    record_artifact_version,
    serialize_artifact_version,
)
from ....services.operation_runtime import register_operation_actions
from ....modules.operations.interfaces.dependencies import get_operation_service
from ....services.observability.run_events import classify_failure
from ...novel_creation_workspace import (
    STAGE_LABELS,
    STAGE_ORDER,
    add_run_event,
    complete_run,
    confirm_run,
    create_run,
    creation_artifact_dependencies,
    derive_stage,
    fail_run,
    list_creation_artifacts,
    patch_creation_artifact,
    patch_session,
    _requested_volume_count,
    save_compact_concepts,
    save_stage,
    serialize_run,
    serialize_creation_artifact,
    serialize_session,
    set_creation_artifact_locks,
    undo_creation_artifact,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


class StageModelResponseError(RuntimeError):
    """Carries model-attempt metadata into the deterministic fallback path."""

    def __init__(self, message: str, *, attempt: int = 1) -> None:
        super().__init__(message)
        self.attempt = max(1, int(attempt))


def _repair_provenance(raw: str, method: str, warning: str) -> dict[str, Any]:
    return {
        "result_mode": "repaired",
        "warning": warning,
        "repair_method": method,
        "original_response_excerpt": raw[:12_000],
        "_diagnostic_raw": raw,
    }


def _safe_partial_stage(
    raw: str,
    stage: str,
    baseline: dict[str, Any],
    draft: dict[str, Any],
) -> dict[str, Any] | None:
    parsed, _method = parse_json_object_detailed(raw)
    if not isinstance(parsed, dict):
        return None
    partial = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
    if not isinstance(partial, dict):
        return None
    try:
        data = _normalize_stage_data(stage, partial, baseline)
        _validate_stage(stage, data)
        _validate_author_requirements(stage, data, baseline, draft)
    except Exception:
        return None
    return data if data != baseline else None


def _safe_partial_concepts(
    raw: str,
    *,
    expected_count: int,
    draft: dict[str, Any],
) -> list[dict[str, Any]] | None:
    parsed, _method = parse_json_object_detailed(raw)
    if not isinstance(parsed, dict):
        return None
    payload = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
    rows = payload.get("concepts") if isinstance(payload.get("concepts"), list) else []
    if not rows:
        return None
    safe = deepcopy(_safe_compact_concepts(draft))
    while len(safe) < expected_count:
        safe.append(deepcopy(safe[-1] if safe else {}))
    merged = safe[:expected_count]
    for index, row in enumerate(rows[:expected_count]):
        if not isinstance(row, dict):
            continue
        protagonist = dict(merged[index].get("protagonist_seed") or {})
        protagonist.update(row.get("protagonist_seed") if isinstance(row.get("protagonist_seed"), dict) else {})
        merged[index].update(row)
        merged[index]["protagonist_seed"] = protagonist
    try:
        cards = _validate_compact_concepts(merged, expected_count=expected_count)
        _validate_author_requirements("concepts", {"options": cards}, {}, draft)
    except Exception:
        return None
    return cards


def _raise_if_task_cancelled() -> None:
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError


def _ensure_stage_not_cancelled(
    db: Session,
    run: NovelCreationStageRun | None,
) -> None:
    """Fence every model/save boundary against both task and durable cancellation."""
    _raise_if_task_cancelled()
    if run is None:
        return
    db.refresh(run)
    if run.status in {"cancelled", "paused"}:
        raise asyncio.CancelledError
    if run.operation_id:
        operation = (
            db.query(OperationRun)
            .filter(OperationRun.id == run.operation_id)
            .populate_existing()
            .first()
        )
        if operation is not None and operation.status == "cancelled":
            raise asyncio.CancelledError


def _is_transient_transport_error(exc: Exception) -> bool:
    message = str(exc).lower()
    failure_class = classify_failure(message)
    if failure_class in {"auth", "quota_or_rate_limit"}:
        return False
    return failure_class in {"network", "timeout"} or any(token in message for token in (
        "incomplete chunked read",
        "peer closed connection",
        "connection closed",
        "connection reset",
        "remote protocol error",
        "server disconnected",
        "unexpected eof",
    ))


def _normalize_worldbuilding(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [deepcopy(item) for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key, child in value.items():
        if isinstance(child, dict):
            item = deepcopy(child)
            item.setdefault("title", _text(key))
            item.setdefault("dimension", _text(key))
            if not _text(item.get("content")):
                item["content"] = _author_text(item.get("summary") or item.get("description") or child)
        else:
            item = {"title": _text(key), "dimension": _text(key), "content": _author_text(child)}
        rows.append(item)
    return rows


def _normalize_characters(data: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    source_rows = _dict_rows(data.get("characters"))
    base_rows = _dict_rows(baseline.get("characters"))
    if not source_rows:
        source_rows = deepcopy(base_rows)
    base_by_name = {_text(row.get("name")): row for row in base_rows if _text(row.get("name"))}
    characters: list[dict[str, Any]] = []
    for index, source in enumerate(source_rows):
        name = _text(source.get("name"))
        base = base_by_name.get(name) or (base_rows[index] if index < len(base_rows) else {})
        item = {**deepcopy(base), **deepcopy(source)}
        item["name"] = name or _text(base.get("name")) or f"角色{index + 1}"
        profile = {**deepcopy(base.get("profile") if isinstance(base.get("profile"), dict) else {}), **deepcopy(item.get("profile") if isinstance(item.get("profile"), dict) else {})}
        source_profile = source.get("profile") if isinstance(source.get("profile"), dict) else {}
        role_type = _text(source.get("role_type") or source.get("role") or base.get("role_type"))
        if not role_type:
            role_type = "protagonist" if index == 0 else "supporting"
        goal = _text(
            source.get("goal")
            or source.get("current_goal")
            or source_profile.get("core_motivation")
            or base.get("goal")
            or profile.get("core_motivation")
        )
        item["role_type"] = role_type
        item["goal"] = goal
        item["current_goal"] = goal
        item["background"] = _text(item.get("background") or item.get("position") or item.get("status"))
        if not _text(profile.get("core_motivation")):
            profile["core_motivation"] = goal
        item["profile"] = profile
        characters.append(item)
    characters = _dedupe_dicts(characters, lambda item: _text(item.get("name")).casefold())
    relationships = _dict_rows(data.get("relationships"), name_field="id") or _dict_rows(baseline.get("relationships"), name_field="id")
    relationships = _dedupe_dicts(
        relationships,
        lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
    )
    return {**deepcopy(baseline), **deepcopy(data), "characters": characters, "relationships": relationships}


def _normalize_locations(data: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    entries = (
        _dict_rows(data.get("entries"), name_field="title")
        + _dict_rows(baseline.get("entries"), name_field="title")
    )
    entries = _dedupe_dicts(entries, lambda item: _text(item.get("title")).casefold())
    relations = (
        _dict_rows(data.get("relations"), name_field="id")
        + _dict_rows(baseline.get("relations"), name_field="id")
    )
    relations = _dedupe_dicts(
        relations,
        lambda item: (
            _text(item.get("source_title")).casefold(),
            _text(item.get("target_title")).casefold(),
            _text(item.get("relation_type")).casefold(),
        ),
    )
    return {**deepcopy(baseline), **deepcopy(data), "entries": entries, "relations": relations}


def _chapter_range(value: Any) -> tuple[int | None, int | None]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None, None
    numbers = re.findall(r"\d+", _text(value))
    if len(numbers) >= 2:
        return int(numbers[0]), int(numbers[1])
    return None, None


def _normalize_macro_outline(data: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    normalized = {**deepcopy(baseline), **deepcopy(data)}
    source_volumes = _dict_rows(data.get("volumes"), name_field="title")
    base_volumes = _dict_rows(baseline.get("volumes"), name_field="title")
    if not source_volumes:
        source_volumes = deepcopy(base_volumes)
    requested_count = int(baseline.get("requested_volume_count") or 0)
    if requested_count:
        source_volumes = source_volumes[:requested_count]
        if len(source_volumes) < requested_count:
            source_volumes.extend(deepcopy(base_volumes[len(source_volumes):requested_count]))
    volumes: list[dict[str, Any]] = []
    for index, source in enumerate(source_volumes):
        base = base_volumes[index] if index < len(base_volumes) else {}
        item = {**deepcopy(base), **deepcopy(source)}
        parsed_start, parsed_end = _chapter_range(item.get("chapters") or item.get("range"))
        start = item.get("start_chapter") or parsed_start or base.get("start_chapter")
        end = item.get("end_chapter") or parsed_end or base.get("end_chapter")
        try:
            item["start_chapter"] = int(start)
            item["end_chapter"] = int(end)
        except (TypeError, ValueError):
            item["start_chapter"] = 0
            item["end_chapter"] = 0
        item["summary"] = _text(item.get("summary") or item.get("core_function") or item.get("focus") or item.get("climax") or base.get("summary"))
        item["title"] = _text(item.get("title")) or f"第{index + 1}卷"
        volumes.append(item)
    normalized["volumes"] = volumes
    normalized["stage_plan"] = _dict_rows(normalized.get("stage_plan"), name_field="name") or [
        {
            "name": item["title"],
            "range": [item["start_chapter"], item["end_chapter"]],
            "promise": item["summary"],
        }
        for item in volumes
    ]
    return normalized


def _chapter_number(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        numbers = re.findall(r"\d+", _text(value))
        return int(numbers[0]) if numbers else fallback


def _normalize_section(
    section: dict[str, Any],
    base: dict[str, Any],
    *,
    chapter_id: str,
    chapter_number: int,
    scene_number: int,
) -> dict[str, Any]:
    item = {**deepcopy(base), **deepcopy(section)}
    item["client_id"] = _text(item.get("client_id")) or f"{chapter_id}-section-{scene_number}"
    item["parent_client_id"] = chapter_id
    item["node_type"] = "section"
    item["sort_order"] = _chapter_number(item.get("sort_order"), scene_number)
    item["title"] = _text(item.get("title")) or f"第{chapter_number}章 · 场景{scene_number}"
    item["summary"] = _text(item.get("summary") or item.get("planned_summary") or item.get("purpose"))
    item["planned_summary"] = _text(item.get("planned_summary") or item.get("summary"))
    base_metadata = base.get("metadata") if isinstance(base.get("metadata"), dict) else {}
    source_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    metadata = {**deepcopy(base_metadata), **deepcopy(source_metadata)}
    metadata["scene_number"] = _chapter_number(metadata.get("scene_number"), scene_number)
    metadata["purpose"] = _text(metadata.get("purpose") or item.get("purpose") or item.get("summary")) or "推进本章目标"
    metadata["location"] = _text(metadata.get("location")) or "地点待定"
    metadata["timeline"] = _text(metadata.get("timeline")) or f"第{chapter_number}章第{scene_number}场"
    metadata["pov_character"] = _text(metadata.get("pov_character")) or "主角"
    metadata["characters"] = metadata.get("characters") if isinstance(metadata.get("characters"), list) else [metadata["pov_character"]]
    metadata["entry_state"] = _text(metadata.get("entry_state")) or "承接上一场景"
    metadata["exit_state"] = _text(metadata.get("exit_state")) or "产生新的行动压力"
    metadata["emotional_residue"] = _text(metadata.get("emotional_residue")) or "情绪推动下一场景"
    metadata["unresolved_actions"] = metadata.get("unresolved_actions") if isinstance(metadata.get("unresolved_actions"), list) else ["追踪本场景产生的新问题"]
    item["metadata"] = metadata
    return item


def _normalize_opening_outline(data: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    source_chapters = _dict_rows(data.get("chapters"), name_field="title")
    base_chapters = _dict_rows(baseline.get("chapters"), name_field="title")
    if base_chapters:
        source_chapters = (source_chapters + [{} for _ in range(len(base_chapters))])[:len(base_chapters)]
    chapters: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    top_sections = _dict_rows(data.get("sections"), name_field="title")
    base_sections = _dict_rows(baseline.get("sections"), name_field="title")
    for index, source in enumerate(source_chapters):
        base = base_chapters[index] if index < len(base_chapters) else {}
        original_id = _text(source.get("client_id"))
        chapter_number = _chapter_number(source.get("chapter_number") or source.get("chapter") or source.get("number"), index + 1)
        chapter_id = original_id or _text(base.get("client_id")) or f"chapter-{chapter_number:02d}"
        chapter = {**deepcopy(base), **deepcopy(source)}
        nested_sections = _dict_rows(chapter.pop("sections", None), name_field="title")
        chapter["client_id"] = chapter_id
        chapter["chapter_number"] = chapter_number
        chapter["node_type"] = "chapter"
        chapter["sort_order"] = _chapter_number(chapter.get("sort_order"), chapter_number)
        chapter["title"] = _text(chapter.get("title")) or f"第{chapter_number}章 未命名事件"
        chapter["summary"] = _text(chapter.get("summary") or chapter.get("planned_summary") or chapter.get("beat"))
        chapter["planned_summary"] = _text(chapter.get("planned_summary") or chapter.get("summary"))
        chapters.append(chapter)

        chapter_aliases = {chapter_id, str(chapter_number), f"chapter-{chapter_number:02d}"}
        if original_id:
            chapter_aliases.add(original_id)
        matching = nested_sections or [
            item for item in top_sections
            if _text(item.get("parent_client_id")) in chapter_aliases
        ]
        base_chapter_id = _text(base.get("client_id")) or chapter_id
        fallback_sections = [item for item in base_sections if _text(item.get("parent_client_id")) == base_chapter_id]
        if len(matching) not in range(2, 7) and fallback_sections:
            matching = fallback_sections
        for scene_index, raw_section in enumerate(matching[:6], start=1):
            base_section = fallback_sections[scene_index - 1] if scene_index <= len(fallback_sections) else {}
            sections.append(_normalize_section(
                raw_section,
                base_section,
                chapter_id=chapter_id,
                chapter_number=chapter_number,
                scene_number=scene_index,
            ))
    return {
        **deepcopy(baseline),
        **deepcopy(data),
        "opening_chapter_count": len(chapters),
        "chapters": chapters,
        "sections": sections,
        "section_rule": "每章2至6个场景事件",
    }


def _normalize_stage_data(stage: str, data: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    base = deepcopy(baseline) if isinstance(baseline, dict) else {}
    source = {} if _looks_like_cli_metadata(data) else deepcopy(data)
    normalized = {**base, **source}
    if stage == "world_style":
        for field in _WORLD_STYLE_TEXT_FIELDS:
            normalized[field] = _author_text(normalized.get(field))
        normalized["worldbuilding"] = _normalize_worldbuilding(normalized.get("worldbuilding"))
    elif stage == "characters":
        normalized = _normalize_characters(source, base)
    elif stage == "locations":
        normalized = _normalize_locations(source, base)
    elif stage == "macro_outline":
        normalized = _normalize_macro_outline(source, base)
    elif stage == "opening_outline":
        normalized = _normalize_opening_outline(source, base)
    return normalized


def _session(db: Session, session_id: str) -> NovelCreationSession | None:
    return db.query(NovelCreationSession).filter(NovelCreationSession.id == session_id).first()


def _free_opencode_candidates(model: str) -> list[str]:
    # A stage run is pinned to the model selected when it was submitted.
    # Never turn an availability, quota, or configuration failure into an
    # implicit model choice on the author's behalf.
    return [model]


async def _stream_model_text(
    *,
    messages: list[dict[str, Any]],
    model: str,
    temperature: float,
    max_tokens: int,
    extra_body: dict[str, Any] | None,
) -> tuple[str, int]:
    operation_id = current_operation_id()
    for attempt in (1, 2):
        _raise_if_task_cancelled()
        chunks: list[str] = []
        emitted_chars = 0
        last_report_at = 0.0
        try:
            generator = LLMGateway.stream_chat_completion(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=0,
                # The gateway handles pre-output failures. This outer attempt
                # additionally restarts a whole request after a partial stream
                # was closed, which is safe because stage data is not persisted
                # until it has passed contract validation.
                retry=0,
                extra_body=extra_body,
            )
            async for chunk in generator:
                _raise_if_task_cancelled()
                chunks.append(chunk)
                emitted_chars += len(chunk)
                now = time.monotonic()
                if operation_id and now - last_report_at >= 2:
                    last_report_at = now
                    record_operation_signal(
                        operation_id,
                        "output",
                        {"output_chars": emitted_chars, "attempt": attempt},
                        message="模型正在生成并校验立项内容",
                    )
            _raise_if_task_cancelled()
            return "".join(chunks), attempt
        except Exception as exc:
            if attempt == 1 and _is_transient_transport_error(exc):
                if operation_id:
                    record_operation_signal(
                        operation_id,
                        "retry",
                        {"attempt": 2, "failure_class": classify_failure(str(exc)) or "network"},
                        message="模型连接中断，正在使用同一模型完整重试一次",
                    )
                continue
            raise
    raise RuntimeError("模型流式调用未完成")


async def _generate_compact_concepts_with_fallback(
    session: NovelCreationSession,
    model: str,
    *,
    context_manifest: Any,
    on_fallback: Any,
    input_snapshot: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    del on_fallback  # Compatibility with the existing call site/event contract.
    return await _generate_compact_concepts(
        session,
        model,
        context_manifest=context_manifest,
        input_snapshot=input_snapshot,
    )


async def _repair_json_with_model(
    *,
    raw: str,
    error: Exception,
    model: str,
    contract: str,
    max_tokens: int,
    extra_body: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, int, str | None]:
    _raise_if_task_cancelled()
    system = (
        "你是司命的阶段结构修复器。只修复 JSON 语法和结构契约，不改写作者事实、专名、"
        "已确认内容或创作方向。只输出一个 JSON 对象，不要解释。"
    )
    user = (
        f"结构契约：{contract}\n"
        f"校验错误：{str(error)[:1000]}\n"
        "请把下面的模型原始输出修复为合法结构；无法确定的内容保持原样，不要另写故事。\n"
        f"原始输出：{raw[:120_000]}"
    )
    repaired, attempt = await _stream_model_text(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=model,
        temperature=0,
        max_tokens=max_tokens,
        extra_body=extra_body,
    )
    _raise_if_task_cancelled()
    parsed, method = parse_json_object_detailed(repaired)
    return parsed, attempt, method


async def _generate_compact_concepts(
    session: NovelCreationSession,
    model: str,
    *,
    context_manifest: Any | None = None,
    input_snapshot: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Generate decision-ready concepts, never a complete project blueprint."""
    draft = deepcopy(input_snapshot) if isinstance(input_snapshot, dict) else (session.draft_json if isinstance(session.draft_json, dict) else {})
    interview = draft.get("interview") if isinstance(draft.get("interview"), dict) else {}
    author = _author_context(draft)
    author_led = author["creation_mode"] == "author_led"
    expected_count = 1 if author_led else 3
    instruction = _text(draft.get("_refinement_instruction"))
    context = {
        "brief": _text(session.user_brief),
        "form": draft.get("form") or {},
        "author_source": author,
        "current_stage_data": ((draft.get("stages") or {}).get("concepts") or {}).get("data"),
        "interview_history": interview.get("history") or [],
        "interview_reason": _text(interview.get("reason")),
        "refinement_instruction": instruction,
    }
    from ....modules.creation.interfaces.dependencies import render_creation_prompt

    system = render_creation_prompt(
        task_kind="整理作者方案" if author_led else "生成三套轻量创意方向",
        task_rules=(
            ("只生成恰好一张作者方案卡，不生成替代故事。作者原文、专名、因果、结局方向和锁定要求都是不可改写的事实；只补全空白。"
             if author_led else
             "只生成恰好三张轻量创意卡，不生成完整世界观、配角表、卷纲或章节细纲。三张卡必须遵守作者约束，并在故事发动机、冲突结构和开篇压力上有实质差异。")
            + "如果提供了调整要求，只调整当前创意阶段，不影响其他阶段。"
        ),
    )
    shape = {
        "concepts": [{
            "title": "不超过20字的标题",
            "subtitle": "一句定位",
            "logline": "不超过120字的一句话梗概",
            "protagonist_seed": {"name": "主角名", "identity": "身份", "goal": "即时目标", "lack": "内在缺口"},
            "world_hook": "不超过100字的世界钩子",
            "core_conflict": "不超过100字的核心冲突",
            "story_engine": "持续推进故事的机制",
            "opening_hook": "不超过100字的开篇钩子",
            "differentiators": ["差异点一", "差异点二"],
            "risks": ["一个创作风险"]
        }]
    }
    user = (
        f"请严格返回恰好{expected_count}张{'作者方案卡' if author_led else '创意卡'}，字段必须与下列 JSON 结构一致。"
        + ("方案必须忠实整理作者已经想好的内容，不得随机替换故事。\n" if author_led else "每张卡应在数百字内可读完，三张卡不得只是改标题。\n")
        + f"输出结构：{json.dumps(shape, ensure_ascii=False)}\n"
        f"作者上下文：{json.dumps(context, ensure_ascii=False)}"
    )
    from ....services.content_store import content_root

    with activate_context_manifest(context_manifest) if context_manifest else nullcontext():
        _raise_if_task_cancelled()
        raw, attempt = await _stream_model_text(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=model,
            temperature=0.8,
            max_tokens=3200,
            extra_body=LLMGateway.local_cli_extra_body(
                model,
                cwd=str(content_root()),
                base={"moshu_task_type": "planning", "storage_target": "session_draft"},
            ),
        )
    _raise_if_task_cancelled()
    try:
        if not raw:
            raise ValueError("模型没有返回轻量创意卡")
        parsed, parse_method = parse_json_object_detailed(raw)
        if not isinstance(parsed, dict):
            raise ValueError("模型返回的轻量创意卡不是有效 JSON")
        payload = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
        cards = _validate_compact_concepts(payload.get("concepts"), expected_count=expected_count)
        _validate_author_requirements("concepts", {"options": cards}, {}, draft)
        metadata = {"attempt": attempt, "result_mode": "model", "warning": None}
        if parse_method != "direct":
            metadata.update(_repair_provenance(
                raw,
                "deterministic_json",
                "模型原始回复存在 JSON 语法问题，系统已确定性修复并保留可识别内容",
            ))
        return cards, metadata
    except Exception as parse_error:
        try:
            repaired, repair_attempt, repair_parse_method = await _repair_json_with_model(
                raw=raw,
                error=parse_error,
                model=model,
                contract=f"顶层 concepts 数组必须恰好包含 {expected_count} 张卡，字段与示例完全一致",
                max_tokens=3200,
                extra_body=LLMGateway.local_cli_extra_body(
                    model,
                    cwd=str(content_root()),
                    base={"moshu_task_type": "planning", "storage_target": "session_draft"},
                ),
            )
            if not isinstance(repaired, dict):
                raise ValueError("结构修复没有返回 JSON 对象")
            payload = repaired.get("data") if isinstance(repaired.get("data"), dict) else repaired
            cards = _validate_compact_concepts(payload.get("concepts"), expected_count=expected_count)
            _raise_if_task_cancelled()
            _validate_author_requirements("concepts", {"options": cards}, {}, draft)
            metadata = {
                "attempt": attempt + repair_attempt,
                **_repair_provenance(raw, "model_json", "模型原始回复格式不合法，已使用同一模型完成一次结构修复"),
            }
            if repair_parse_method not in {None, "direct"}:
                metadata["repair_method"] = "model_json+deterministic_json"
            return cards, metadata
        except Exception as repair_error:
            safe_cards = None if instruction else _safe_partial_concepts(
                raw,
                expected_count=expected_count,
                draft=draft,
            )
            if safe_cards is not None:
                return safe_cards, {
                    "attempt": attempt + 1,
                    "result_mode": "deterministic_fallback",
                    "warning": "模型返回的部分创意结构不可用，系统已保留可识别内容并补齐安全默认值",
                    "repair_method": "safe_partial_draft",
                    "repair_error": str(repair_error)[:1000],
                    "original_response_excerpt": raw[:12_000],
                    "_diagnostic_raw": raw,
                }
            raise StageModelResponseError(
                f"{parse_error}；同模型结构修复失败：{repair_error}",
                attempt=attempt + 1,
            ) from repair_error


async def _enhance_with_model(
    session: NovelCreationSession,
    stage: str,
    baseline: dict[str, Any],
    model: str,
    *,
    context_manifest: Any | None = None,
    input_snapshot: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    draft = deepcopy(input_snapshot) if isinstance(input_snapshot, dict) else (session.draft_json if isinstance(session.draft_json, dict) else {})
    instruction = _text(draft.get("_refinement_instruction"))
    context = {
        "form": draft.get("form"),
        "author_source": _author_context(draft),
        "selected_concept_id": draft.get("selected_concept_id"),
        "current_stage_data": ((draft.get("stages") or {}).get(stage) or {}).get("data"),
        "confirmed_stages": {
            name: value.get("data")
            for name, value in (draft.get("stages") or {}).items()
            if isinstance(value, dict) and value.get("status") == "confirmed"
        },
        "baseline": baseline,
        "refinement_instruction": instruction,
    }
    from ....modules.creation.interfaces.dependencies import render_creation_prompt

    system = render_creation_prompt(
        task_kind=f"深化阶段：{STAGE_LABELS.get(stage, stage)}",
        task_rules=(
            "只深化当前阶段的 baseline，顶层只返回 data 字段；"
            "保留作者原文、锁定要求、已确认事实和专名，不提前生成下游阶段。"
            "调整要求只作用于当前阶段；没有明确授权时不得改动其他内容。"
        ),
    )
    user = (
        f"当前阶段：{STAGE_LABELS.get(stage, stage)}\n"
        f"结构契约：{_stage_contract(stage)}\n"
        "请在保留作者约束和已确认事实的前提下，深化 baseline；不要改变已经确认的专名。\n"
        + (f"作者本次调整要求：{instruction}\n" if instruction else "")
        + f"上下文：{json.dumps(context, ensure_ascii=False)}"
    )
    from ....services.content_store import content_root

    with activate_context_manifest(context_manifest) if context_manifest else nullcontext():
        _raise_if_task_cancelled()
        raw, attempt = await _stream_model_text(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=model,
            temperature=0.65,
            max_tokens=12000 if stage == "opening_outline" else 6000,
            extra_body=LLMGateway.local_cli_extra_body(
                model,
                cwd=str(content_root()),
                base={"moshu_task_type": "planning", "storage_target": "session_draft"},
            ),
        )
    _raise_if_task_cancelled()
    try:
        if not raw:
            raise ValueError("没有收到模型的文字回复")
        parsed, parse_method = parse_json_object_detailed(raw)
        if not isinstance(parsed, dict):
            raise ValueError("模型返回的阶段 JSON 格式不合法")
        data = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
        _validate_author_requirements(stage, data, baseline, draft)
        data = _normalize_stage_data(stage, data, baseline)
        _validate_stage(stage, data)
        _validate_author_requirements(stage, data, baseline, draft)
        metadata = {"attempt": attempt, "result_mode": "model", "warning": None}
        if parse_method != "direct":
            metadata.update(_repair_provenance(
                raw,
                "deterministic_json",
                "模型原始回复存在 JSON 语法问题，系统已确定性修复并保留可识别内容",
            ))
        return data, metadata
    except Exception as parse_error:
        try:
            repaired, repair_attempt, repair_parse_method = await _repair_json_with_model(
                raw=raw,
                error=parse_error,
                model=model,
                contract=_stage_contract(stage),
                max_tokens=12000 if stage == "opening_outline" else 6000,
                extra_body=LLMGateway.local_cli_extra_body(
                    model,
                    cwd=str(content_root()),
                    base={"moshu_task_type": "planning", "storage_target": "session_draft"},
                ),
            )
            if not isinstance(repaired, dict):
                raise ValueError("结构修复没有返回 JSON 对象")
            data = repaired.get("data") if isinstance(repaired.get("data"), dict) else repaired
            _raise_if_task_cancelled()
            _validate_author_requirements(stage, data, baseline, draft)
            data = _normalize_stage_data(stage, data, baseline)
            _validate_stage(stage, data)
            _validate_author_requirements(stage, data, baseline, draft)
            metadata = {
                "attempt": attempt + repair_attempt,
                **_repair_provenance(raw, "model_json", "模型原始回复格式不合法，已使用同一模型完成一次结构修复"),
            }
            if repair_parse_method not in {None, "direct"}:
                metadata["repair_method"] = "model_json+deterministic_json"
            return data, metadata
        except Exception as repair_error:
            safe_data = None if instruction else _safe_partial_stage(raw, stage, baseline, draft)
            if safe_data is not None:
                return safe_data, {
                    "attempt": attempt + 1,
                    "result_mode": "deterministic_fallback",
                    "warning": "模型返回的部分阶段结构不可用，系统已保留可识别内容并补齐安全默认值",
                    "repair_method": "safe_partial_draft",
                    "repair_error": str(repair_error)[:1000],
                    "original_response_excerpt": raw[:12_000],
                    "_diagnostic_raw": raw,
                }
            raise StageModelResponseError(
                f"{parse_error}；同模型结构修复失败：{repair_error}",
                attempt=attempt + 1,
            ) from repair_error


async def get_novel_creation_session(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session_id = _text(args.get("session_id"))
    session = _session(db, session_id)
    if not session:
        return {"tool": "get_novel_creation_session", "status": "skipped", "detail": "Session not found", "data": None}
    return {
        "tool": "get_novel_creation_session",
        "status": "ok",
        "detail": "Novel creation session loaded",
        "data": serialize_session(session),
    }


async def get_creation_session(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    """Stable conversational alias for the resumable creation session contract."""
    result = await get_novel_creation_session(db, project_id, args)
    return {**result, "tool": "get_creation_session"}


async def get_creation_snapshot(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    if not session:
        return {"tool": "get_creation_snapshot", "status": "skipped", "detail": "Session not found", "data": None}
    return {
        "tool": "get_creation_snapshot",
        "status": "ok",
        "detail": "Creation snapshot loaded",
        "data": {
            "revision": int(session.revision or 0),
            "session": serialize_session(session),
            "artifacts": list_creation_artifacts(session),
        },
    }


async def get_creation_operation(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    operation_id = _text(args.get("operation_id"))
    if not operation_id and _text(args.get("run_id")):
        run = db.query(NovelCreationStageRun).filter(NovelCreationStageRun.id == _text(args.get("run_id"))).first()
        operation_id = _text(getattr(run, "operation_id", ""))
    operation = get_operation_service().get(operation_id, include_events=True) if operation_id else None
    if not operation:
        return {"tool": "get_creation_operation", "status": "skipped", "detail": "Operation not found", "data": None}
    return {"tool": "get_creation_operation", "status": "ok", "detail": "Creation operation loaded", "data": operation}


async def patch_creation_session_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    if not session:
        return {"tool": "patch_creation_session", "status": "skipped", "detail": "Session not found", "data": None}
    if args.get("expected_revision") is None or int(args["expected_revision"]) != int(session.revision or 0):
        return _revision_error("patch_creation_session", session)
    changes = args.get("changes") if isinstance(args.get("changes"), dict) else {}
    try:
        patch_session(session, changes)
        commit_session(db)
        return {"tool": "patch_creation_session", "status": "ok", "detail": "Creation session patched", "data": serialize_session(session)}
    except Exception as exc:
        db.rollback()
        return {"tool": "patch_creation_session", "status": "error", "detail": str(exc), "data": None}


async def get_creation_artifact(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    stage = _text(args.get("artifact"))
    if not session:
        return {"tool": "get_creation_artifact", "status": "skipped", "detail": "Session not found", "data": None}
    try:
        return {"tool": "get_creation_artifact", "status": "ok", "detail": "Artifact loaded", "data": serialize_creation_artifact(session, stage)}
    except ValueError as exc:
        return {"tool": "get_creation_artifact", "status": "error", "detail": str(exc), "data": None}


async def list_creation_artifacts_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    if not session:
        return {"tool": "list_creation_artifacts", "status": "skipped", "detail": "Session not found", "data": None}
    return {
        "tool": "list_creation_artifacts",
        "status": "ok",
        "detail": "Creation artifacts loaded",
        "data": {"revision": int(session.revision or 0), "artifacts": list_creation_artifacts(session)},
    }


async def get_creation_dependencies(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    if not session:
        return {"tool": "get_creation_dependencies", "status": "skipped", "detail": "Session not found", "data": None}
    try:
        return {
            "tool": "get_creation_dependencies",
            "status": "ok",
            "detail": "Artifact dependencies loaded",
            "data": creation_artifact_dependencies(session, _text(args.get("artifact"))),
        }
    except ValueError as exc:
        return {"tool": "get_creation_dependencies", "status": "error", "detail": str(exc), "data": None}


async def get_creation_dependency_graph_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    if not session:
        return {"tool": "get_creation_dependency_graph", "status": "skipped", "detail": "Session not found", "data": None}
    data = creation_dependency_graph(session)
    commit_session(db)
    return {"tool": "get_creation_dependency_graph", "status": "ok", "detail": "Dependency graph loaded", "data": data}


async def validate_creation_consistency_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    if not session:
        return {"tool": "validate_creation_consistency", "status": "skipped", "detail": "Session not found", "data": None}
    data = validate_creation_consistency(session)
    commit_session(db)
    return {
        "tool": "validate_creation_consistency",
        "status": "ok" if data["valid"] else "warning",
        "detail": "Creation data is consistent" if data["valid"] else "Creation data needs attention",
        "data": data,
    }


def _revision_error(tool: str, session: NovelCreationSession) -> dict[str, Any]:
    return {
        "tool": tool,
        "status": "error",
        "detail": "Novel creation session revision conflict",
        "data": {"failure_class": "revision_conflict", "current_revision": int(session.revision or 0)},
    }


async def patch_creation_artifact_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    if not session:
        return {"tool": "patch_creation_artifact", "status": "skipped", "detail": "Session not found", "data": None}
    if args.get("expected_revision") is None or int(args["expected_revision"]) != int(session.revision or 0):
        return _revision_error("patch_creation_artifact", session)
    try:
        result = patch_creation_artifact(
            session,
            _text(args.get("artifact")),
            args.get("changes") if isinstance(args.get("changes"), list) else [],
            source=_text(args.get("source")) or "assistant",
            validator=_validate_stage,
        )
        commit_session(db)
        return {"tool": "patch_creation_artifact", "status": "ok", "detail": "Artifact patched", "data": result}
    except Exception as exc:
        db.rollback()
        return {"tool": "patch_creation_artifact", "status": "error", "detail": str(exc), "data": None}


async def _set_creation_locks(db: Session, args: dict[str, Any], *, locked: bool) -> dict[str, Any]:
    tool = "lock_creation_fields" if locked else "unlock_creation_fields"
    session = _session(db, _text(args.get("session_id")))
    if not session:
        return {"tool": tool, "status": "skipped", "detail": "Session not found", "data": None}
    if args.get("expected_revision") is None or int(args["expected_revision"]) != int(session.revision or 0):
        return _revision_error(tool, session)
    try:
        artifact = set_creation_artifact_locks(
            session,
            _text(args.get("artifact")),
            args.get("paths") if isinstance(args.get("paths"), list) else [],
            locked=locked,
        )
        commit_session(db)
        return {"tool": tool, "status": "ok", "detail": "Artifact locks updated", "data": artifact}
    except Exception as exc:
        db.rollback()
        return {"tool": tool, "status": "error", "detail": str(exc), "data": None}


async def lock_creation_fields(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    return await _set_creation_locks(db, args, locked=True)


async def unlock_creation_fields(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    return await _set_creation_locks(db, args, locked=False)


async def undo_creation_artifact_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    if not session:
        return {"tool": "undo_creation_artifact", "status": "skipped", "detail": "Session not found", "data": None}
    if args.get("expected_revision") is None or int(args["expected_revision"]) != int(session.revision or 0):
        return _revision_error("undo_creation_artifact", session)
    try:
        result = undo_creation_artifact(session, _text(args.get("artifact")))
        commit_session(db)
        return {"tool": "undo_creation_artifact", "status": "ok", "detail": "Latest artifact change undone", "data": result}
    except Exception as exc:
        db.rollback()
        return {"tool": "undo_creation_artifact", "status": "error", "detail": str(exc), "data": None}


async def list_creation_entities_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    if not session:
        return {"tool": "list_creation_entities", "status": "skipped", "detail": "Session not found", "data": None}
    entities = list_creation_entity_records(
        session,
        artifact=_text(args.get("artifact")) or None,
        entity_type=_text(args.get("entity_type")) or None,
        include_deleted=bool(args.get("include_deleted", False)),
    )
    commit_session(db)
    return {
        "tool": "list_creation_entities",
        "status": "ok",
        "detail": "Creation entities loaded",
        "data": {"revision": int(session.revision or 0), "entities": entities},
    }


async def get_creation_entity_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    entity = get_creation_entity_record(db, _text(args.get("entity_id")))
    if not entity:
        return {"tool": "get_creation_entity", "status": "skipped", "detail": "Entity not found", "data": None}
    return {"tool": "get_creation_entity", "status": "ok", "detail": "Creation entity loaded", "data": serialize_creation_entity(entity)}


async def patch_creation_entity_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    entity = get_creation_entity_record(db, _text(args.get("entity_id")))
    if not entity:
        return {"tool": "patch_creation_entity", "status": "skipped", "detail": "Entity not found", "data": None}
    session = _session(db, entity.session_id)
    if args.get("expected_revision") is None or int(args["expected_revision"]) != int(session.revision or 0):
        return _revision_error("patch_creation_entity", session)
    try:
        result = patch_creation_entity_record(
            session,
            entity,
            args.get("changes") if isinstance(args.get("changes"), list) else [],
            expected_revision=int(args["expected_revision"]),
            source=_text(args.get("source")) or "assistant",
        )
        commit_session(db)
        return {"tool": "patch_creation_entity", "status": "ok", "detail": "Creation entity patched", "data": result}
    except Exception as exc:
        db.rollback()
        return {"tool": "patch_creation_entity", "status": "error", "detail": str(exc), "data": None}


async def delete_creation_entity_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    entity = get_creation_entity_record(db, _text(args.get("entity_id")))
    if not entity:
        return {"tool": "delete_creation_entity", "status": "skipped", "detail": "Entity not found", "data": None}
    session = _session(db, entity.session_id)
    if args.get("expected_revision") is None or int(args["expected_revision"]) != int(session.revision or 0):
        return _revision_error("delete_creation_entity", session)
    try:
        result = delete_creation_entity_record(
            session,
            entity,
            expected_revision=int(args["expected_revision"]),
            source=_text(args.get("source")) or "assistant",
        )
        commit_session(db)
        return {"tool": "delete_creation_entity", "status": "ok", "detail": "Creation entity deleted", "data": result}
    except Exception as exc:
        db.rollback()
        return {"tool": "delete_creation_entity", "status": "error", "detail": str(exc), "data": None}


async def list_creation_artifact_versions_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    artifact = _text(args.get("artifact"))
    if not session:
        return {"tool": "list_creation_artifact_versions", "status": "skipped", "detail": "Session not found", "data": None}
    current = serialize_creation_artifact(session, artifact)
    if isinstance(current.get("data"), dict):
        record_artifact_version(
            session,
            artifact,
            current["data"],
            revision=int(session.revision or 0),
            status=current["status"],
            source=current["source"],
            change_type="legacy_baseline",
        )
        commit_session(db)
    versions = list_artifact_versions(
        db,
        session_id=session.id,
        artifact=artifact,
        limit=int(args.get("limit") or 100),
    )
    return {
        "tool": "list_creation_artifact_versions",
        "status": "ok",
        "detail": "Artifact history loaded",
        "data": {"revision": int(session.revision or 0), "versions": [serialize_artifact_version(item) for item in versions]},
    }


async def get_creation_artifact_diff_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    version = get_artifact_version(db, _text(args.get("version_id")))
    if not version:
        return {"tool": "get_creation_artifact_diff", "status": "skipped", "detail": "Version not found", "data": None}
    try:
        return {
            "tool": "get_creation_artifact_diff",
            "status": "ok",
            "detail": "Artifact diff loaded",
            "data": artifact_version_diff(db, version, against_version_id=_text(args.get("against_version_id")) or None),
        }
    except Exception as exc:
        return {"tool": "get_creation_artifact_diff", "status": "error", "detail": str(exc), "data": None}


async def restore_creation_artifact_version_tool(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    version = get_artifact_version(db, _text(args.get("version_id")))
    if not version:
        return {"tool": "restore_creation_artifact_version", "status": "skipped", "detail": "Version not found", "data": None}
    session = _session(db, version.session_id)
    if args.get("expected_revision") is None or int(args["expected_revision"]) != int(session.revision or 0):
        return _revision_error("restore_creation_artifact_version", session)
    try:
        result = restore_creation_artifact_version_record(
            session, version, expected_revision=int(args["expected_revision"]),
        )
        commit_session(db)
        return {"tool": "restore_creation_artifact_version", "status": "ok", "detail": "Artifact version restored", "data": result}
    except Exception as exc:
        db.rollback()
        return {"tool": "restore_creation_artifact_version", "status": "error", "detail": str(exc), "data": None}


async def import_creation_material(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    session = _session(db, _text(args.get("session_id")))
    if not session:
        return {"tool": "import_creation_material", "status": "skipped", "detail": "Session not found", "data": None}
    file_path = Path(_text(args.get("file_path"))).expanduser()
    if not file_path.exists() or not file_path.is_file():
        return {"tool": "import_creation_material", "status": "error", "detail": "导入文件不存在", "data": None}
    try:
        import_run, replayed = create_material_import(
            db,
            session,
            filename=file_path.name,
            raw=file_path.read_bytes(),
            model=_text(args.get("model")) or None,
            source_message_id=_text(args.get("source_message_id")) or None,
        )
        commit_session(db)
        if not replayed and import_run.status == "queued":
            task = asyncio.create_task(run_material_import(import_run.id, _text(args.get("model")) or None))
            if import_run.operation_id:
                register_operation_actions(import_run.operation_id, cancel=task.cancel)
        return {
            "tool": "import_creation_material",
            "status": "ok",
            "detail": "已恢复同一文件导入" if replayed else "原始文件已保存，持久导入任务已开始",
            "data": serialize_material_import(import_run),
        }
    except Exception as exc:
        db.rollback()
        return {"tool": "import_creation_material", "status": "error", "detail": str(exc), "data": None}


async def preview_creation_import(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    import_run = db.get(NovelCreationMaterialImport, _text(args.get("import_id")))
    if not import_run:
        return {"tool": "preview_creation_import", "status": "skipped", "detail": "Import run not found", "data": None}
    session_id = _text(args.get("session_id"))
    if session_id and import_run.session_id != session_id:
        return {"tool": "preview_creation_import", "status": "error", "detail": "导入任务不属于当前立项会话", "data": None}
    return {
        "tool": "preview_creation_import",
        "status": "ok",
        "detail": "导入预览已就绪" if import_run.status == "waiting_user" else "导入状态已加载",
        "data": serialize_material_import(import_run),
    }


async def apply_creation_import(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    import_run = db.get(NovelCreationMaterialImport, _text(args.get("import_id")))
    if not import_run:
        return {"tool": "apply_creation_import", "status": "skipped", "detail": "Import run not found", "data": None}
    try:
        result = apply_material_import(
            db,
            import_run,
            selected_artifacts=[_text(value) for value in (args.get("selected_artifacts") or [])],
            strategy=_text(args.get("strategy")) or "merge",
            expected_revision=int(args.get("expected_revision")),
        )
        return {"tool": "apply_creation_import", "status": "ok", "detail": "所选导入内容已原子写入", "data": result}
    except RuntimeError as exc:
        if str(exc) == "revision_conflict":
            return {"tool": "apply_creation_import", "status": "conflict", "detail": "立项 revision 已变化，请刷新预览", "data": None}
        return {"tool": "apply_creation_import", "status": "error", "detail": str(exc), "data": None}
    except Exception as exc:
        db.rollback()
        return {"tool": "apply_creation_import", "status": "error", "detail": str(exc), "data": None}


async def generate_novel_creation_stage(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    from ....services.novel_creation_stage_execution import execute_novel_creation_stage

    return await execute_novel_creation_stage(
        db,
        project_id,
        args,
        ensure_not_cancelled=_ensure_stage_not_cancelled,
        generate_concepts=_generate_compact_concepts_with_fallback,
        normalize_stage=_normalize_stage_data,
        enhance_with_model=_enhance_with_model,
        model_response_error=StageModelResponseError,
    )


async def submit_novel_creation_stage(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    return await submit_creation_stage(
        db, args, normalize_stage=_normalize_stage_data, validate_stage=_validate_stage,
    )


async def confirm_creation_artifact(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    """Confirm exactly one artifact without implicitly generating another artifact."""
    session_id = _text(args.get("session_id"))
    artifact = _text(args.get("artifact"))
    session = _session(db, session_id)
    if not session:
        return {"tool": "confirm_creation_artifact", "status": "skipped", "detail": "Session not found", "data": None}
    data = args.get("data")
    if not isinstance(data, dict):
        current = serialize_creation_artifact(session, artifact)
        data = current.get("data") if isinstance(current.get("data"), dict) else None
    if not isinstance(data, dict):
        return {"tool": "confirm_creation_artifact", "status": "conflict", "detail": "Artifact has no generated data to confirm", "data": None}
    result = await submit_novel_creation_stage(db, project_id, {
        "session_id": session_id,
        "stage": artifact,
        "data": data,
        "confirm": True,
        "source": _text(args.get("source")) or "author",
        "expected_revision": args.get("expected_revision"),
    })
    if result.get("status") == "ok":
        run = (
            db.query(NovelCreationStageRun)
            .filter(NovelCreationStageRun.session_id == session_id, NovelCreationStageRun.stage == artifact)
            .order_by(NovelCreationStageRun.created_at.desc())
            .first()
        )
        if run and confirm_run(db, run):
            commit_session(db)
        if run and run.operation_id:
            get_operation_service().complete_author_confirmation(run.operation_id)
    return {**result, "tool": "confirm_creation_artifact"}


async def _generate_creation_artifact(
    db: Session,
    project_id: str,
    args: dict[str, Any],
    *,
    operation: str,
    tool: str,
) -> dict[str, Any]:
    payload = {
        **args,
        "stage": _text(args.get("artifact") or args.get("stage")),
        "operation": operation,
        "use_model": bool(args.get("use_model", True)),
        "auto_confirm": False,
    }
    if operation == "refine" and not _text(payload.get("instruction")):
        return {"tool": tool, "status": "error", "detail": "instruction is required for refinement", "data": None}
    result = await generate_novel_creation_stage(db, project_id, payload)
    return {**result, "tool": tool}


async def generate_creation_artifact(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    return await _generate_creation_artifact(db, project_id, args, operation="generate", tool="generate_creation_artifact")


async def refine_creation_artifact(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    return await _generate_creation_artifact(db, project_id, args, operation="refine", tool="refine_creation_artifact")


async def regenerate_creation_artifact(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    return await _generate_creation_artifact(db, project_id, args, operation="regenerate", tool="regenerate_creation_artifact")


async def _creation_operation_action(args: dict[str, Any], *, action: str, tool: str) -> dict[str, Any]:
    operation_id = _text(args.get("operation_id"))
    if not operation_id:
        return {"tool": tool, "status": "error", "detail": "operation_id is required", "data": None}
    status, payload = await get_operation_service().action(operation_id, action)
    if status == "not_found":
        return {"tool": tool, "status": "skipped", "detail": "Operation not found", "data": None}
    if status != "ok":
        return {"tool": tool, "status": "conflict", "detail": "Operation does not support this action in its current state", "data": payload}
    return {"tool": tool, "status": "ok", "detail": f"Operation action completed: {action}", "data": payload}


async def cancel_creation_operation(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    return await _creation_operation_action(args, action="cancel", tool="cancel_creation_operation")


async def pause_creation_operation(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    return await _creation_operation_action(args, action="pause", tool="pause_creation_operation")


async def resume_creation_operation(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    return await _creation_operation_action(args, action="continue", tool="resume_creation_operation")


async def retry_creation_operation(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    return await _creation_operation_action(args, action="retry_current_unit", tool="retry_creation_operation")


async def validate_creation_session(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    result = await validate_creation_consistency_tool(db, project_id, args)
    return {**result, "tool": "validate_creation_session"}


async def finalize_creation_session(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    """Validate a session and idempotently create its formal project."""
    validation = await validate_creation_consistency_tool(db, project_id, args)
    if validation.get("status") not in {"ok"}:
        return {
            "tool": "finalize_creation_session",
            "status": "conflict",
            "detail": "Creation session has unresolved consistency issues",
            "data": validation.get("data"),
        }
    from .novel_creation import apply_novel_blueprint

    result = await apply_novel_blueprint(db, project_id, {**args, "mode": "auto"})
    return {**result, "tool": "finalize_creation_session"}
