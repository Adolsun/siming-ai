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
from .records import normalize_candidate
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







def candidate_recovery_context(
    db: Session, run: CatalogingChapterRun, *, include_payloads: bool = True,
    plan_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return retained plan metadata; tool callers can page through full records."""
    accepted = []
    candidates = db.query(CatalogingCandidate).filter(
        CatalogingCandidate.chapter_run_id == run.id,
        CatalogingCandidate.status != "rejected",
    ).order_by(CatalogingCandidate.sort_order, CatalogingCandidate.id).all()
    for row in candidates:
        payload = _cataloging_candidate_payload(row)
        retained = {key: payload[key] for key in (
            "id", "name", "title", "source_name", "target_name", "relationship_type",
            "scene_number", "node_type", "source_labels", "coverage_manifest", "scenes", "character_bindings", "worldbuilding_bindings",
        ) if key in payload}
        if row.item_type == "chapter_link":
            retained.update({key: payload[key] for key in (
                "characters", "worldbuilding_titles", "locations", "items", "events", "outline_title",
            ) if key in payload})
        if include_payloads:
            retained = payload
        accepted.append({"candidate_id": row.id, "item_type": row.item_type, "status": row.status,
                         "target_id": row.target_id, "target_name": row.target_name,
                         "scene_number": payload.get("scene_number"), "payload": retained})
    if plan_report is None:
        from .plan_validation import inspect_complete_plan
        plan_report = inspect_complete_plan(db, run, rows=candidates)
    return {
        **plan_report,
        "coverage_repairs": declared_worldbuilding_reference_repairs(candidates),
        "accepted_candidates": accepted,
        "scene_repair": scene_repair_context(db, run) if include_payloads else None,
        "read_full_candidates": {"tool": "list_cataloging_candidates", "arguments": {
            "job_id": run.job_id, "chapter_run_id": run.id, "limit": 2,
        }},
    }


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
        sources = payload.get("source_labels")
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
