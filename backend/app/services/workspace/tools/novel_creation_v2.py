"""Workspace tools for the resumable V2 novel creation workbench."""
from __future__ import annotations

from app.architecture.uow import commit_session

import asyncio
import json
import re
import time
from contextlib import nullcontext
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from ....modules.model_runtime.application.execution import model_executor as LLMGateway
from ...operation_runtime import current_operation_id, record_operation_signal
from ....core.json_repair import parse_json_object
from ....database.models import NovelCreationSession, NovelCreationStageRun, OperationRun
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
from ....services.observability.run_events import classify_failure
from ...novel_creation_workspace import (
    STAGE_LABELS,
    STAGE_ORDER,
    add_run_event,
    complete_run,
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
    if run.status == "cancelled":
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
) -> tuple[dict[str, Any] | None, int]:
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
    return parse_json_object(repaired), attempt


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
        parsed = parse_json_object(raw)
        if not isinstance(parsed, dict):
            raise ValueError("模型返回的轻量创意卡不是有效 JSON")
        payload = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
        cards = _validate_compact_concepts(payload.get("concepts"), expected_count=expected_count)
        _validate_author_requirements("concepts", {"options": cards}, {}, draft)
        return cards, {
            "attempt": attempt,
            "result_mode": "model",
            "warning": None,
        }
    except Exception as parse_error:
        try:
            repaired, repair_attempt = await _repair_json_with_model(
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
            return cards, {
                "attempt": attempt + repair_attempt,
                "result_mode": "repaired",
                "warning": "模型原始回复格式不合法，已使用同一模型完成一次结构修复",
            }
        except Exception as repair_error:
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
        parsed = parse_json_object(raw)
        if not isinstance(parsed, dict):
            raise ValueError("模型返回的阶段 JSON 格式不合法")
        data = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
        _validate_author_requirements(stage, data, baseline, draft)
        data = _normalize_stage_data(stage, data, baseline)
        _validate_stage(stage, data)
        _validate_author_requirements(stage, data, baseline, draft)
        return data, {"attempt": attempt, "result_mode": "model", "warning": None}
    except Exception as parse_error:
        try:
            repaired, repair_attempt = await _repair_json_with_model(
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
            return data, {
                "attempt": attempt + repair_attempt,
                "result_mode": "repaired",
                "warning": "模型原始回复格式不合法，已使用同一模型完成一次结构修复",
            }
        except Exception as repair_error:
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
    session_id = _text(args.get("session_id"))
    stage = _text(args.get("stage"))
    session = _session(db, session_id)
    if not session:
        return {"tool": "submit_novel_creation_stage", "status": "skipped", "detail": "Session not found", "data": None}
    if stage not in STAGE_ORDER:
        return {"tool": "submit_novel_creation_stage", "status": "skipped", "detail": "Unknown stage", "data": None}
    expected_revision = args.get("expected_revision")
    if expected_revision is not None and int(session.revision or 0) != int(expected_revision):
        return {
            "tool": "submit_novel_creation_stage",
            "status": "error",
            "detail": "Novel creation session revision conflict",
            "data": {
                "failure_class": "revision_conflict",
                "current_revision": int(session.revision or 0),
                "session": serialize_session(session),
            },
        }
    data = args.get("data")
    if not isinstance(data, dict):
        data = derive_stage(session, stage)
    try:
        data = _normalize_stage_data(stage, data)
        _validate_stage(stage, data)
        save_stage(session, stage, data, confirm=bool(args.get("confirm", True)), source=_text(args.get("source")) or "author")
        commit_session(db)
        return {
            "tool": "submit_novel_creation_stage",
            "status": "ok",
            "detail": f"{STAGE_LABELS[stage]}已保存",
            "data": serialize_session(session),
        }
    except Exception as exc:
        db.rollback()
        return {"tool": "submit_novel_creation_stage", "status": "error", "detail": str(exc), "data": None}
