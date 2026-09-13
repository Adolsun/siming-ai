"""Validation helpers for deciding when a cataloging chapter is writable."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from sqlalchemy.orm import Session

from ...database.models import (
    CatalogingChapterRun,
    Character,
    ChapterCharacter,
    OutlineNode,
    WorldbuildingEntry,
)
from ...database.query_filters import current_worldbuilding_clause
from ...modules.continuity.domain.outline_character_contract import outline_character_ids
from ..story_granularity import CandidateCoverage, inspect_candidate_coverage_items

def _candidate_context(items: list[Any]) -> tuple[str, str]:
    for item in items:
        if isinstance(item, dict):
            run_id = str(item.get("chapter_run_id") or "").strip()
            chapter_id = str(item.get("chapter_id") or "").strip()
        else:
            run_id = str(getattr(item, "chapter_run_id", "") or "").strip()
            chapter_id = str(getattr(item, "chapter_id", "") or "").strip()
        if run_id or chapter_id:
            return run_id, chapter_id
    return "", ""




def _value_items(value):
    return value if isinstance(value, list) else [] if value is None else [value]


_MISSING_ITEM_LABELS = {
    "source characters missing from coverage_manifest.characters": "原文角色未进入章节覆盖清单",
    "source worldbuilding missing from coverage_manifest.worldbuilding": (
        "原文设定未进入章节覆盖清单"
    ),
    "source relationships missing from coverage_manifest.relationships": (
        "原文角色关系未进入章节覆盖清单"
    ),
    "source character profile evidence missing from coverage_manifest.character_profiles": (
        "原文角色档案信息未进入角色资料候选"
    ),
    "character_create/update for new declared characters": "新角色缺少可落库的角色资料候选",
    "relationship endpoints without character profiles": "角色关系引用了没有资料卡的角色",
    "relationship endpoints missing from coverage_manifest.characters": (
        "角色关系中的人物未进入章节角色清单"
    ),
    "chapter summary has fewer than 40 non-whitespace characters": (
        "章节摘要少于40个非空白字符，不能作为可靠建档摘要"
    ),
    "chapter_overview scenes disagree with coverage_manifest.scene_count": (
        "计划场景数与章节覆盖清单不一致"
    ),
}


def describe_candidate_coverage_missing(items: Iterable[str]) -> list[str]:
    """Translate persistence diagnostics while preserving actionable detail."""

    result: list[str] = []
    for item in items:
        raw = str(item or "").strip()
        prefix, separator, detail = raw.partition(": ")
        label = _MISSING_ITEM_LABELS.get(prefix)
        if not label:
            result.append(raw)
            continue
        result.append(f"{label}：{detail}" if separator and detail else label)
    return result


def candidate_coverage_error_message(
    coverage: CandidateCoverage,
    *,
    prefix: str = "候选覆盖不完整",
) -> str:
    missing = describe_candidate_coverage_missing(coverage.cli_parity_missing)
    details = _candidate_coverage_identity_details(coverage)
    messages = [*missing, *details]
    return prefix if not messages else f"{prefix}：" + "；".join(messages)


def candidate_coverage_review_message(coverage: CandidateCoverage) -> str:
    warnings = describe_candidate_coverage_missing(coverage.review_warnings)
    if not warnings:
        return ""
    return "候选已保留，需要核对模型抽取的原文线索：" + "；".join(warnings)


def candidate_coverage_should_retry(coverage: CandidateCoverage) -> bool:
    """Every hard gap is eligible for an incremental model repair turn."""

    return bool(coverage.cli_parity_missing)


def _candidate_coverage_identity_details(coverage: CandidateCoverage) -> list[str]:
    pairs = (
        (
            set(coverage.declared_character_identities)
            - set(coverage.character_state_identities),
            "缺少角色状态候选",
        ),
        (
            set(coverage.declared_worldbuilding_identities)
            - set(coverage.worldbuilding_candidate_identities),
            "缺少世界观候选或既有设定关联",
        ),
        (
            set(coverage.declared_relationship_identities)
            - set(coverage.relationship_candidate_identities),
            "缺少角色关系候选",
        ),
        (
            set(coverage.declared_character_profile_identities)
            - set(coverage.character_profile_candidate_identities),
            "缺少角色资料候选",
        ),
        (
            set(coverage.declared_character_identities)
            - set(coverage.chapter_link_character_identities),
            "缺少角色章节关联",
        ),
        (
            set(coverage.declared_worldbuilding_identities)
            - set(coverage.chapter_link_worldbuilding_identities),
            "缺少世界观章节关联",
        ),
    )
    return [
        f"{label}：" + "、".join(sorted(values))
        for values, label in pairs
        if values
    ]


def _identity(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def _character_identity_index(
    db: Session,
    project_id: str,
    *,
    created_before: Any = None,
) -> tuple[list[Character], set[str], dict[str, str], dict[str, str]]:
    character_query = db.query(Character).filter(Character.project_id == project_id)
    if created_before is not None:
        character_query = character_query.filter(Character.created_at <= created_before)
    characters = character_query.all()
    by_id = {row.id: _identity(row.name) for row in characters if _identity(row.name)}
    identity_map = {canonical: canonical for canonical in by_id.values()}
    # Model-selected database IDs are explicit references, not display names.
    # Validate coverage against the same project-scoped records used to apply.
    identity_map.update({_identity(identity): canonical for identity, canonical in by_id.items()})
    return characters, set(by_id.values()), identity_map, by_id


def _candidate_payload(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
        return dict(payload)
    raw = getattr(item, "edited_payload", None) or getattr(item, "raw_payload", None)
    if isinstance(raw, dict):
        return dict(raw)
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _candidate_type(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("item_type") or item.get("type") or "").strip()
    return str(getattr(item, "item_type", "") or "").strip()


def _candidate_status(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("status") or "").strip()
    return str(getattr(item, "status", "") or "").strip()


def _candidate_character_name(item: Any) -> str:
    payload = _candidate_payload(item)
    return _identity(
        payload.get("name")
        or payload.get("character_name")
        or payload.get("target_name")
        or getattr(item, "target_name", "")
    )








def _candidate_character_identity_map(
    items: list[Any],
    base_map: dict[str, str],
    by_id: dict[str, str],
) -> dict[str, str]:
    """Compare coverage using the exact IDs declared by current model cards."""

    targets: dict[str, set[str]] = defaultdict(set)
    for alias, canonical in base_map.items():
        targets[alias].add(canonical)
    for item in items:
        if _candidate_status(item) == "rejected":
            continue
        if _candidate_type(item) not in {"character_create", "character_update"}:
            continue
        payload = _candidate_payload(item)
        raw_name = _identity(
            payload.get("name")
            or payload.get("character_name")
            or payload.get("target_name")
        )
        target_id = str(
            payload.get("id")
            or payload.get("client_id")
            or getattr(item, "target_id", "")
            or ""
        ).strip()
        canonical = by_id.get(target_id) or base_map.get(raw_name, raw_name)
        if not canonical:
            continue
        targets[canonical].add(canonical)
        if raw_name:
            targets[raw_name].add(canonical)
        if target_id:
            targets[_identity(target_id)].add(canonical)
    resolved = {
        alias: next(iter(canonicals))
        for alias, canonicals in targets.items()
        if len(canonicals) == 1
    }
    resolved.update({_identity(identity): canonical for identity, canonical in by_id.items()})
    return resolved





def _relationship_endpoints(keys: Iterable[str]) -> set[str]:
    endpoints: set[str] = set()
    for key in keys:
        source, separator, remainder = str(key or "").partition("|")
        target, _, _relationship_type = remainder.partition("|") if separator else ("", "", "")
        if source:
            endpoints.add(source)
        if target:
            endpoints.add(target)
    return endpoints


def _canonical_relationship(key: str, identity_map: dict[str, str]) -> str:
    source, separator, remainder = str(key or "").partition("|")
    target, target_separator, relationship_type = (
        remainder.partition("|") if separator else ("", "", "")
    )
    if not separator or not target_separator:
        return str(key or "")
    return "|".join((
        identity_map.get(source, source),
        identity_map.get(target, target),
        relationship_type,
    ))


def _canonicalize_coverage(
    coverage: CandidateCoverage,
    identity_map: dict[str, str],
) -> CandidateCoverage:
    def identities(values: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            sorted({identity_map.get(value, value) for value in values if value})
        )

    def relationships(values: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            sorted({_canonical_relationship(value, identity_map) for value in values if value})
        )

    declared = identities(coverage.declared_character_identities)
    states = identities(coverage.character_state_identities)
    profiles = identities(coverage.character_profile_candidate_identities)
    declared_profiles = identities(coverage.declared_character_profile_identities)
    links = identities(coverage.chapter_link_character_identities)
    declared_relationships = relationships(coverage.declared_relationship_identities)
    relationship_candidates = relationships(coverage.relationship_candidate_identities)
    return replace(
        coverage,
        declared_character_count=len(declared),
        character_state_count=len(states),
        declared_character_profile_count=len(declared_profiles),
        character_profile_candidate_count=len(profiles),
        declared_relationship_count=len(declared_relationships),
        relationship_candidate_count=len(relationship_candidates),
        declared_character_identities=declared,
        character_state_identities=states,
        declared_character_profile_identities=declared_profiles,
        character_profile_candidate_identities=profiles,
        chapter_link_character_identities=links,
        declared_relationship_identities=declared_relationships,
        relationship_candidate_identities=relationship_candidates,
    )


def _append_identity_warning(
    warnings: list[str],
    values: set[str],
    label: str,
) -> None:
    if values:
        warnings.append(f"{label}：" + "、".join(sorted(values)))


def _reconcile_candidate_policy(
    coverage: CandidateCoverage,
    items: list[Any],
    *,
    existing_characters: set[str],
    existing_worldbuilding: set[str],
) -> tuple[CandidateCoverage, set[str]]:
    """Apply the cataloging repair policy directly to the canonical coverage.

    This used to be installed by a package-import monkey patch. Keeping it in
    the validator makes API, local CLI and MCP callers execute the same code.
    """

    unresolved: set[str] = set()

    declared_characters = set(coverage.declared_character_identities)
    states = set(coverage.character_state_identities) & declared_characters
    declared_profiles = (
        set(coverage.declared_character_profile_identities) - unresolved
    )
    candidate_profiles = (
        set(coverage.character_profile_candidate_identities) - unresolved
    )
    # Incremental repair deliberately does not replay chapter_summary.  A
    # valid profile card for a character already declared by that retained
    # summary therefore extends the effective character_profiles manifest.
    # Requiring the old summary to declare the repair beforehand made a
    # successfully generated character_create/update impossible to accept.
    declared_profiles.update(candidate_profiles & declared_characters)
    profiles = candidate_profiles & declared_profiles
    declared_relationships = set(coverage.declared_relationship_identities)
    relationships = (
        set(coverage.relationship_candidate_identities) & declared_relationships
    )
    character_links = (
        set(coverage.chapter_link_character_identities) & declared_characters
    )

    declared_worldbuilding = set(coverage.declared_worldbuilding_identities)
    raw_worldbuilding = set(coverage.worldbuilding_candidate_identities)
    worldbuilding_links = set(coverage.chapter_link_worldbuilding_identities)
    covered_worldbuilding = raw_worldbuilding | (
        declared_worldbuilding & worldbuilding_links & existing_worldbuilding
    )
    covered_worldbuilding &= declared_worldbuilding
    worldbuilding_links &= declared_worldbuilding

    warnings = list(coverage.review_warnings)
    _append_identity_warning(
        warnings,
        set(coverage.character_state_identities) - declared_characters,
        "角色状态候选未写入 coverage_manifest.characters",
    )
    _append_identity_warning(
        warnings,
        set(coverage.character_profile_candidate_identities) - declared_profiles,
        "角色资料候选未写入 coverage_manifest.character_profiles",
    )
    _append_identity_warning(
        warnings,
        set(coverage.relationship_candidate_identities) - declared_relationships,
        "角色关系候选未写入 coverage_manifest.relationships",
    )
    _append_identity_warning(
        warnings,
        raw_worldbuilding - declared_worldbuilding,
        "世界观候选未写入 coverage_manifest.worldbuilding",
    )
    _append_identity_warning(
        warnings,
        set(coverage.chapter_link_character_identities) - declared_characters,
        "章节关联包含清单外角色",
    )
    _append_identity_warning(
        warnings,
        set(coverage.chapter_link_worldbuilding_identities) - declared_worldbuilding,
        "章节关联包含清单外世界观",
    )
    _append_identity_warning(
        warnings,
        unresolved,
        "身份未确认角色按章节线索保留，不强制建立永久角色卡",
    )

    return replace(
        coverage,
        character_state_count=len(states),
        declared_character_profile_count=len(declared_profiles),
        character_profile_candidate_count=len(profiles),
        declared_relationship_count=len(declared_relationships),
        relationship_candidate_count=len(relationships),
        declared_worldbuilding_count=len(declared_worldbuilding),
        worldbuilding_candidate_count=len(covered_worldbuilding),
        character_state_identities=tuple(sorted(states)),
        declared_character_profile_identities=tuple(sorted(declared_profiles)),
        character_profile_candidate_identities=tuple(sorted(profiles)),
        relationship_candidate_identities=tuple(sorted(relationships)),
        declared_worldbuilding_identities=tuple(sorted(declared_worldbuilding)),
        worldbuilding_candidate_identities=tuple(sorted(covered_worldbuilding)),
        chapter_link_character_identities=tuple(sorted(character_links)),
        chapter_link_worldbuilding_identities=tuple(sorted(worldbuilding_links)),
        review_warnings=tuple(dict.fromkeys(warnings)),
    ), unresolved


def _prepare_database_coverage(
    db: Session,
    project_id: str,
    items: list[Any],
    coverage: CandidateCoverage,
) -> tuple[CandidateCoverage, list[Character], set[str], dict[str, str], set[str], Any]:
    run_id, _chapter_id = _candidate_context(items)
    run = (
        db.query(CatalogingChapterRun).filter(CatalogingChapterRun.id == run_id).first()
        if run_id else None
    )
    source_baseline = (run.started_at or run.created_at) if run is not None else None
    characters, existing, database_identity_map, by_id = _character_identity_index(
        db,
        project_id,
        created_before=None,
    )
    identity_map = _candidate_character_identity_map(items, database_identity_map, by_id)
    coverage = _canonicalize_coverage(coverage, identity_map)
    entry_query = db.query(WorldbuildingEntry).filter(
        WorldbuildingEntry.project_id == project_id,
        current_worldbuilding_clause(WorldbuildingEntry.status),
    )
    existing_worldbuilding = {
        title for row in entry_query.all() if (title := _identity(row.title))
    }
    coverage, unresolved = _reconcile_candidate_policy(
        coverage,
        items,
        existing_characters=existing,
        existing_worldbuilding=existing_worldbuilding,
    )
    return coverage, characters, existing, identity_map, unresolved, source_baseline


def validate_candidate_source_character_grounding(
    db: Session, project_id: str, run: CatalogingChapterRun, normalized: dict[str, Any],
) -> None:
    from .plan_contract import validate_plan_references
    validate_plan_references(db, project_id, run, normalized)


def _referential_missing(
    coverage: CandidateCoverage,
    existing: set[str],
    unresolved: set[str],
) -> list[str]:
    missing = list(coverage.persistence_missing)
    declared = set(coverage.declared_character_identities)
    profiles = set(coverage.character_profile_candidate_identities)
    new_without_profiles = sorted(declared - existing - profiles - unresolved)
    if new_without_profiles:
        missing.append(
            "character_create/update for new declared characters: "
            + "、".join(new_without_profiles)
        )
    endpoints = _relationship_endpoints([
        *coverage.declared_relationship_identities,
        *coverage.relationship_candidate_identities,
    ])
    unknown = sorted(endpoints - (existing | profiles) - unresolved)
    if unknown:
        missing.append(
            "relationship endpoints without character profiles: " + "、".join(unknown)
        )
    undeclared = sorted(endpoints - declared)
    if undeclared:
        missing.append(
            "relationship endpoints missing from coverage_manifest.characters: "
            + "、".join(undeclared)
        )
    return missing


def _source_review_warnings(
    db: Session, project_id: str, items: list[Any], coverage: CandidateCoverage,
    characters: list[Character], identity_map: dict[str, str], source_baseline: Any,
) -> list[str]:
    # Semantic completeness belongs to the same Agent that reads the chapter.
    # The application checks the plan's explicit coverage and real references.
    warnings = list(coverage.review_warnings)
    for item in items:
        if _candidate_type(item) == "chapter_summary" and _candidate_status(item) != "rejected":
            summary = _candidate_payload(item).get("summary_text", "")
            if len("".join(str(summary).split())) < 40:
                warnings.append("chapter summary has fewer than 40 non-whitespace characters")
    return warnings


def _outline_reference_missing(db: Session, project_id: str, items: list[Any]) -> list[str]:
    existing = {row[0] for row in db.query(Character.id).filter(Character.project_id == project_id).all()}
    new_ids = {
        client_id for item in items
        if _candidate_type(item) == "character_create" and _candidate_status(item) not in {"rejected", "apply_failed"}
        and isinstance(client_id := _candidate_payload(item).get("client_id"), str)
    }
    missing: list[str] = []
    for item in items:
        if _candidate_type(item) not in {"outline_create", "outline_update"} or _candidate_status(item) == "rejected":
            continue
        payload = _candidate_payload(item)
        try:
            expected = set(outline_character_ids(payload))
        except ValueError as exc:
            missing.append(str(exc))
            continue
        if not expected.issubset(existing | new_ids):
            missing.append("大纲 character_ids 无有效角色或同批新角色：" + "、".join(sorted(expected - existing - new_ids)))
        if _candidate_status(item) != "applied":
            continue
        node = db.get(OutlineNode, getattr(item, "target_id", None))
        if node is None or node.project_id != project_id:
            missing.append("大纲人物绑定目标不存在或不属于当前作品")
            continue
        actual = {link.character_id for link in node.linked_characters}
        if node.node_type == "chapter":
            expected.update(row[0] for row in db.query(ChapterCharacter.character_id).filter(
                ChapterCharacter.chapter_id == getattr(item, "chapter_id", None),
            ).all())
        if (not expected.issubset(actual) or not actual.issubset(existing)
                or (node.node_type == "section" and actual != expected)):
            missing.append(f"大纲人物绑定未完成写入：{node.id}")
    return missing


def inspect_candidate_coverage(
    candidates: Iterable[Any],
    *,
    db: Session | None = None,
    project_id: str | None = None,
) -> CandidateCoverage:
    """Return shared coverage plus database-aware referential checks.

    The pure coverage contract prevents duplicate cards from satisfying a
    declared count.  With a session, it also guarantees that every newly
    declared character has a stable profile card and that relationships cannot
    manufacture empty character rows as a side effect.
    """

    items = list(candidates)
    coverage = inspect_candidate_coverage_items(items)
    if db is None or not project_id:
        return coverage

    coverage, characters, existing, identity_map, unresolved, source_baseline = (
        _prepare_database_coverage(
            db,
            project_id,
            items,
            coverage,
        )
    )
    missing = [*coverage.persistence_missing, *_referential_missing(coverage, existing, unresolved),
               *_outline_reference_missing(db, project_id, items)]
    review_warnings = _source_review_warnings(
        db,
        project_id,
        items,
        coverage,
        characters,
        identity_map,
        source_baseline,
    )
    if not missing and not review_warnings:
        return coverage
    return replace(
        coverage,
        persistence_missing=tuple(dict.fromkeys(missing)),
        review_warnings=tuple(dict.fromkeys(review_warnings)),
    )
