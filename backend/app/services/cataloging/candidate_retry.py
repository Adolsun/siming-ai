"""Incremental cataloging candidate retry and coverage diagnostics."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ...database.models import CatalogingCandidate, CatalogingChapterRun
from ..story_granularity import normalize_node_type, normalize_section_scene_state
from .candidate_validation import (
    candidate_coverage_error_message,
    candidate_coverage_review_message,
    candidate_coverage_should_retry,
    inspect_candidate_coverage,
)
from .jsonl import normalize_candidate
from .scene_contract import scene_repair_context


def candidate_issue(result: dict[str, Any]) -> dict[str, Any]:
    """Pair the rejected record with its error so the model can correct it."""
    rejected = result.get("bad_line") or ""
    try:
        rejected = json.loads(rejected)
    except (TypeError, ValueError):
        rejected = result.get("bad_line") or ""
    raw = rejected if isinstance(rejected, dict) else {}
    try:
        normalized = normalize_candidate(raw) if raw else {}
    except (TypeError, ValueError):
        normalized = {}
    return {
        "kind": result.get("error_kind") or "candidate_validation",
        "item_type": normalized.get("item_type"),
        "target": normalized.get("target_id") or normalized.get("target_name"),
        "message": str(result.get("error") or "候选未通过校验"),
        "rejected_candidate": rejected,
        "repair_context": result.get("repair_context"),
        "scene_repair": result.get("scene_repair"),
    }


def candidate_issue_summary(issues: list[dict[str, Any]], *, details: bool = False) -> str:
    counts: dict[str, int] = {}
    for issue in issues:
        kind = str(issue.get("kind") or "candidate_validation")
        counts[kind] = counts.get(kind, 0) + 1
    labels = {"jsonl_parse": "行 JSONL 格式错误", "candidate_validation": "条建档候选校验未通过",
              "candidate_processing": "条建档候选处理失败"}
    summary = "；".join(f"{count} {labels[kind]}" for kind, count in counts.items())
    if details and issues:
        summary += "：" + "；".join(str(issue["message"]) for issue in issues)
    return summary


def candidate_retry_reason(
    db: Session,
    run: CatalogingChapterRun,
    issues: list[dict[str, Any]],
    coverage_reason: str,
) -> str:
    """Give the same model the rejected fields AND the cumulative missing work."""
    accepted = []
    candidates = db.query(CatalogingCandidate).filter(
        CatalogingCandidate.chapter_run_id == run.id,
        CatalogingCandidate.status != "rejected",
    ).order_by(CatalogingCandidate.sort_order, CatalogingCandidate.id).all()
    for row in candidates:
        payload = _cataloging_candidate_payload(row)
        accepted.append({"candidate_id": row.id, "item_type": row.item_type,
                         "target_id": row.target_id, "target_name": row.target_name,
                         "scene_number": payload.get("scene_number"), "payload": payload})
    return json.dumps({
        "candidate_errors": issues,
        "coverage_error": coverage_reason,
        "coverage_repairs": declared_worldbuilding_reference_repairs(candidates),
        "accepted_candidates": accepted,
        "scene_repair": scene_repair_context(db, run),
    }, ensure_ascii=False, separators=(",", ":"))


def declared_worldbuilding_reference_repairs(
    candidates: list[CatalogingCandidate],
) -> list[dict[str, Any]]:
    """Point to inconsistent fields using only explicit, accepted model mappings.

    This is diagnostic data, not an alias resolver: it never rewrites a manifest,
    chooses an archive from prose, or allows an invalid chapter link to pass.
    Conflicting mappings are left to the model, not guessed by the application.
    """
    accepted = [
        {"candidate_id": row.id, "item_type": row.item_type, "target_id": row.target_id,
         "payload": _cataloging_candidate_payload(row)}
        for row in candidates if row.status != "rejected"
    ]
    mappings: dict[str, dict[tuple[str, str], str]] = {}
    for row in accepted:
        if row["item_type"] not in {
            "worldbuilding_create", "worldbuilding_update", "worldbuilding_timeline",
        }:
            continue
        payload = row["payload"]
        title = str(payload.get("title") or "").strip()
        target_id = str(row.get("target_id") or payload.get("id") or "")
        sources = payload.get("source_fact_titles")
        if not title or not isinstance(sources, list):
            continue
        for source in sources:
            if isinstance(source, str) and source.strip() and source.strip() != title:
                mappings.setdefault(source.strip(), {})[(target_id, title)] = row["candidate_id"]
    repairs = []
    for row in accepted:
        payload = row["payload"]
        if row["item_type"] == "chapter_summary":
            values = (payload.get("coverage_manifest") or {}).get("worldbuilding") or []
            field, mode = "coverage_manifest.worldbuilding", "coverage_manifest_mode"
        elif row["item_type"] == "chapter_link":
            values = payload.get("worldbuilding_titles") or []
            field, mode = "worldbuilding_titles", "chapter_link_mode"
        else:
            continue
        for value in values:
            targets = mappings.get(value.strip(), {}) if isinstance(value, str) else {}
            if len(targets) != 1:
                continue
            (target_id, title), mapping_id = next(iter(targets.items()))
            repairs.append({
                "candidate_id": row["candidate_id"], "item_type": row["item_type"],
                "field": field, "current_value": value, "model_declared_title": title,
                "model_declared_target_id": target_id or None,
                "mapping_candidate_id": mapping_id, "required_mode": {mode: "replace"},
            })
    return repairs


def append_incremental_candidate_retry(prompt: str, reason: str) -> str:
    return prompt + (
        "\n\n【上一轮校验未通过，执行增量修复】\n"
        f"{reason}\n"
        "本节规则优先于上面的首次生成要求。系统已保留上一轮成功入库的候选；"
        "依据 candidate_errors 中的具体字段错误、coverage_error 中的缺项，以及 "
        "accepted_candidates 中已通过的记录修复；同一候选被拒绝不代表整批没有保存。"
        "coverage_repairs 列出已接受候选之间的字段冲突：世界观映射已保存，"
        "但指定 candidate_id 的摘要或章节关联仍使用原事实称呼。"
        "对照 model_declared_target_id 与 model_declared_title，修正对应 field，"
        "按 required_mode 输出完整摘要覆盖清单或完整章节关联数组，并保留其他内容。"
        "仅重发 mapping_candidate_id 指向的世界观候选不能修复摘要或关联；"
        "若该映射正确且没有其他错误，不要重发它。"
        "rejected_candidate 是本次被拒绝的原始记录，请对照原文修正，不要猜测上轮输出。"
        "若提供 repair_context，按其 target_id 和 field 定位字段，逐字复制 expected_value，"
        "包括末尾标点和空白；它是校验时读取的当前原值，不是摘要。"
        "若 requirement=preserve_and_append，expected_value 是新值必须完整保留的旧文，"
        "不是修正后的完整新值；在它之后追加本章有证据的变化，并将同一旧文填入对应 *_before。"
        "旧文末尾的句号也不能改成分号：例如旧值为‘旧回执。’，新值应为‘旧回执。本章新增：新证物。’，"
        "不能写成‘旧回执；本章新增：新证物。’。不要仅复制旧文而丢掉本章确有依据的新变化。"
        "错误列出的遗漏 ID 只是差集；worldbuilding_create 的 reviewed_existing_ids "
        "仍须包含 worldbuilding_identity_review_required 全部 ID，不能只填写报错列出的缺项。"
        "只输出错误信息明确指出的缺失候选，以及上一轮解析失败、身份不一致或结构错误候选的修正版。\n"
        "chapter_summary 仅在缺失或明确纠正错误覆盖清单时输出；chapter_outline 仅在缺失时输出；"
        "不要重复任何已通过候选，也不要重发完整候选集。\n"
        "仅当 scene_repair.required_repair_type=scene_outline_replace，或 candidate_errors "
        "明确指出场景编号越界/错位时，启用下述完整重排规则；"
        "该字段为 null 且没有场景错误时，禁止重排已有场景，须修复实际报错的角色或世界观等缺项。"
        "场景编号冲突时，下面的完整重排规则优先于所有‘只补缺项’或‘不要重发’规则："
        "对照 scene_repair.source_scenes，重新提交全部 1..N 场景的完整内容；"
        "不能只删越界条目，不能只修最后一个编号，不能遗漏任何源场景事件。"
        "单独输出一个 JSON 对象：{\"type\":\"scene_outline_replace\","
        "\"expected_candidate_ids\":[\"section_candidates中的全部当前候选ID\"],"
        "\"sections\":[全部N条完整的outline_create/section候选]}。"
        "sections 每条必须明确 scene_number，并补全所有场景状态字段。"
        "expected_candidate_ids 必须逐项复制 scene_repair.expected_candidate_ids，"
        "包含所有待退役的越界或重复候选；该数组长度可以大于新 sections 的数量。"
        "系统会原子替换当前完整场景候选集；任一条失败则全部回滚。"
        "原场景保留审计记录，章级大纲和其他业务候选不变。"
        "例如源场景1同时含通话和核验，而旧候选把它拆为1、2时，必须合回场景1，"
        "并依源分场顺序重写后续场景；不能仅把末条5改成4造成中间审批事件丢失。\n"
        "不得任意降低或重写既有 coverage_manifest.scene_count；只有旧清单与 source_scene_count "
        "不一致时，才可用完整 coverage_manifest_mode=replace 修正为该源场景数，不得改动源分场。"
        "如果上一轮把同一身份的别名或近义标题"
        "错误地重复列入 coverage_manifest，或把 stable_profile_change=false 且无稳定档案变化"
        "的已有角色误列为必须更新档案，单独输出一条 chapter_summary，设置 "
        "coverage_manifest_mode=\"replace\"，并提供包含 scene_count、characters、worldbuilding、"
        "relationships、character_profiles 的完整纠正清单；该操作只替换清单，不重发章级大纲。"
        "若事实已归入精确 ID 的世界观规范卡，分开修正两种候选："
        "chapter_summary 的 coverage_manifest.worldbuilding 只列规范卡稳定标题；"
        "另行输出对应 worldbuilding_update 或 worldbuilding_timeline，"
        "在该世界观候选内用 source_fact_titles 字符串数组声明原事实标签。"
        "source_fact_titles 禁止放进 chapter_summary、coverage_manifest 或 chapter_link，"
        "也不能写成 {\"worldbuilding\":[...]} 对象。被拒绝摘要里的这个字段应移除，"
        "摘要和世界观修复必须分别输出为独立候选；不要删掉需要保留的覆盖清单或事实。"
        "不得为补齐错误称呼新建重复卡。"
        "不能为了绕过校验而删掉事实中确实存在的角色、关系、设定或稳定档案变化。"
        "如果既有聚合 chapter_link 含清单外别名、误称或错误端点，单独输出一条 chapter_link，"
        "设置 chapter_link_mode=\"replace\"，并完整提供 characters、worldbuilding_titles、"
        "locations、items、events 五个数组；该操作替换同一条关联，不新增关联记录。"
        "如果错误指出 source worldbuilding 缺失，而该事实已由某个精确 ID 的世界观候选承接，"
        "仅在该世界观候选内补充 source_fact_titles 字符串数组，保留其真实 ID 与稳定标题；"
        "不要把来源映射写进章节摘要，也不得新建别名卡。"
        "错误列出缺失 scene_number 时，"
        "逐个输出对应的 section outline_create，并补齐全部场景状态字段。\n"
        "修复 character_state_update 时仍须读取当前完整角色卡：电话或消息参与者未明示实时地点时"
        "省略 current_location；appearance 或 age 若需变化，提交逐字复制当前值的 *_before "
        "以及本章正文逐字摘录的 *_evidence，否则省略该字段；items_or_assets 若需变化，提交逐字复制当前完整值的 "
        "items_or_assets_before，并让新值逐字包含旧值后再追加状态，"
        "且不得把同场其他人物经手的物件归给当前角色。\n"
        "每行只输出一个标准候选 JSON 对象；不要输出聚合总对象、Markdown、解释或代码块。"
    )


def candidate_coverage_for_run(db: Session, run: CatalogingChapterRun):
    candidates = (
        db.query(CatalogingCandidate)
        .filter(CatalogingCandidate.chapter_run_id == run.id)
        .filter(CatalogingCandidate.status != "rejected")
        .all()
    )
    return inspect_candidate_coverage(candidates, db=db, project_id=run.project_id)


def _cataloging_candidate_payload(candidate: CatalogingCandidate) -> dict[str, Any]:
    try:
        value = json.loads(candidate.edited_payload or candidate.raw_payload or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _scene_repair_details(
    candidates: list[CatalogingCandidate],
    scene_count: int,
) -> list[str]:
    if scene_count <= 1:
        return []
    section_numbers: set[int] = set()
    state_numbers: set[int] = set()
    for candidate in candidates:
        if candidate.item_type not in {"outline_create", "outline_update"}:
            continue
        payload = _cataloging_candidate_payload(candidate)
        if normalize_node_type(payload.get("node_type")) != "section":
            continue
        try:
            scene_number = int(payload.get("scene_number"))
        except (TypeError, ValueError):
            continue
        if scene_number <= 0:
            continue
        section_numbers.add(scene_number)
        if normalize_section_scene_state(payload):
            state_numbers.add(scene_number)
    expected = set(range(1, scene_count + 1))
    details: list[str] = []
    missing_sections = sorted(expected - section_numbers)
    if missing_sections:
        details.append("缺少 section 场景编号：" + "、".join(map(str, missing_sections)))
    missing_states = sorted(expected - state_numbers)
    if missing_states:
        details.append(
            "缺少场景状态字段的 scene_number：" + "、".join(map(str, missing_states))
        )
    return details


def candidate_coverage_error(db: Session, run: CatalogingChapterRun) -> str:
    candidates = (
        db.query(CatalogingCandidate)
        .filter(CatalogingCandidate.chapter_run_id == run.id)
        .filter(CatalogingCandidate.status != "rejected")
        .all()
    )
    coverage = inspect_candidate_coverage(candidates, db=db, project_id=run.project_id)
    if coverage.is_complete:
        return ""
    message = candidate_coverage_error_message(coverage)
    details = _scene_repair_details(candidates, coverage.scene_count)
    return message if not details else message + "；" + "；".join(details)


def candidate_coverage_requires_model_retry(
    db: Session,
    run: CatalogingChapterRun,
) -> bool:
    return candidate_coverage_should_retry(candidate_coverage_for_run(db, run))


def candidate_coverage_review(db: Session, run: CatalogingChapterRun) -> str:
    return candidate_coverage_review_message(candidate_coverage_for_run(db, run))
