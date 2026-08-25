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
    CatalogingFact,
    Chapter,
    Character,
    CharacterAlias,
    WorldbuildingEntry,
)
from ..story_granularity import CandidateCoverage, inspect_candidate_coverage_items

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
    return prefix if not missing else f"{prefix}：" + "；".join(missing)


def candidate_coverage_review_message(coverage: CandidateCoverage) -> str:
    warnings = describe_candidate_coverage_missing(coverage.review_warnings)
    if not warnings:
        return ""
    return "候选已保留，需要核对模型抽取的原文线索：" + "；".join(warnings)


def candidate_coverage_should_retry(coverage: CandidateCoverage) -> bool:
    """Retry the model only when its response is structurally unusable.

    Identity/manifest mismatches are deterministic validation work. Repeating
    the same expensive model call usually recreates the same cards and may
    discard useful output, so those gaps must be repaired or reviewed in place.
    """

    if not coverage.has_chapter_summary or not coverage.has_chapter_outline:
        return True
    if not coverage.narrative_assessed:
        return True
    if not all(
        (
            coverage.has_scene_count_declaration,
            coverage.has_character_declaration,
            coverage.has_worldbuilding_declaration,
            coverage.has_relationship_declaration,
            coverage.has_character_profile_declaration,
        )
    ):
        return True
    return False


def _identity(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def _canonical_display_identity(value: str, identity_map: dict[str, str]) -> str:
    """Resolve provider display labels without merging conflicting people.

    Parentheses normally add an alias or role to one list item, while a slash
    can also mean two separate people.  Parenthetical labels may resolve from
    one unambiguous component; slash labels require every component to resolve
    to the same canonical card.
    """

    raw = _identity(value)
    if not raw:
        return ""
    direct = identity_map.get(raw)
    if direct:
        return direct

    match = re.fullmatch(r"(.+?)[（(]([^（）()]+)[）)]", raw)
    if match:
        components = {_identity(match.group(1)), _identity(match.group(2))}
        anchors = {identity_map[item] for item in components if item in identity_map}
        if len(anchors) == 1:
            return next(iter(anchors))
        return raw

    components = {
        _identity(part)
        for part in re.split(r"[/／|｜、]", raw)
        if _identity(part)
    }
    anchors = {identity_map[item] for item in components if item in identity_map}
    if components and len(anchors) == 1 and all(item in identity_map for item in components):
        return next(iter(anchors))
    return raw


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
    alias_query = db.query(CharacterAlias).filter(CharacterAlias.project_id == project_id)
    if created_before is not None:
        alias_query = alias_query.filter(CharacterAlias.created_at <= created_before)
    aliases = alias_query.all()
    identity_map = {canonical: canonical for canonical in by_id.values()}
    for alias in aliases:
        canonical = by_id.get(alias.character_id)
        alias_identity = _identity(alias.alias)
        if canonical and alias_identity:
            identity_map[alias_identity] = canonical
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


def _candidate_character_identity_map(
    items: list[Any],
    base_map: dict[str, str],
    by_id: dict[str, str],
) -> dict[str, str]:
    """Include aliases from staged character cards without trusting conflicts.

    Candidate aliases are part of the same transactional write set as the
    coverage manifest.  Ignoring them makes a fact such as ``特昂糖`` fail to
    match the staged canonical card ``陆糖 (alias: 特昂糖)``.  An alias claimed
    by multiple cards remains deliberately unresolved.
    """

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
            payload.get("character_id")
            or payload.get("target_id")
            or getattr(item, "target_id", "")
            or ""
        ).strip()
        canonical = by_id.get(target_id) or base_map.get(raw_name, raw_name)
        if not canonical:
            continue
        targets[canonical].add(canonical)
        if raw_name:
            targets[raw_name].add(canonical)
        for alias in _value_items(payload.get("aliases")):
            alias_identity = _identity(alias)
            if alias_identity:
                targets[alias_identity].add(canonical)
    return {
        alias: next(iter(canonicals))
        for alias, canonicals in targets.items()
        if len(canonicals) == 1
    }


def _source_fact_payloads(
    db: Session,
    items: list[Any],
) -> list[tuple[str, dict[str, Any]]]:
    run_id, _chapter_id = _candidate_context(items)
    if not run_id:
        return []
    rows = db.query(CatalogingFact).filter(
        CatalogingFact.chapter_run_id == run_id,
        CatalogingFact.status == "active",
    ).all()
    result: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        try:
            payload = json.loads(row.raw_payload or "{}")
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            result.append((str(row.fact_type or ""), payload))
    return result


def _apply_identity_hints(
    identity_map: dict[str, str],
    facts: list[tuple[str, dict[str, Any]]],
) -> dict[str, str]:
    """Resolve an identity hint only when it has one known card as anchor."""

    result = dict(identity_map)
    for fact_type, payload in facts:
        if fact_type != "identity_hint":
            continue
        names = {
            _identity(item)
            for item in _value_items(payload.get("names") or payload.get("aliases"))
            if _identity(item)
        }
        anchors = {result[name] for name in names if name in result}
        if len(anchors) != 1:
            continue
        canonical = next(iter(anchors))
        for name in names:
            result[name] = canonical
    return result


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
            sorted({_canonical_display_identity(value, identity_map) for value in values if value})
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


def _value_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _fact_names(payload: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in (
        "name",
        "character_name",
        "primary_name",
        "source_name",
        "target_name",
        "characters",
        "character_names",
        "names",
    ):
        for item in _value_items(payload.get(key)):
            if isinstance(item, dict):
                item = item.get("name") or item.get("character_name") or item.get("title")
            identity = _identity(item)
            if identity:
                names.add(identity)
    return names


def _canonical_fact_names(payload: dict[str, Any], identity_map: dict[str, str]) -> set[str]:
    return {
        _canonical_display_identity(name, identity_map)
        for name in _fact_names(payload)
        if name
    }


def _display_identity_references_content(value: str, content: str) -> bool:
    raw = str(value or "").strip()
    if _contains_reference(content, raw):
        return True
    # One-character Chinese names are uncommon but valid. Preserve the
    # stricter threshold for generic references, but accept an exact CJK name.
    if re.fullmatch(r"[\u3400-\u9fff]", raw) and raw in content:
        return True
    parts = {
        part.strip()
        for part in re.split(r"[（()）/／|｜、]", raw)
        if part.strip()
    }
    return any(
        _contains_reference(content, part)
        or (re.fullmatch(r"[\u3400-\u9fff]", part) is not None and part in content)
        for part in parts
    )


def _grounded_fact_names(
    payload: dict[str, Any],
    identity_map: dict[str, str],
    chapter_content: str,
) -> set[str]:
    return {
        _canonical_display_identity(name, identity_map)
        for name in _fact_names(payload)
        if _display_identity_references_content(name, chapter_content)
    }


def _fact_worldbuilding_titles(payload: dict[str, Any]) -> set[str]:
    titles: set[str] = set()
    for key in ("title", "entry_title", "worldbuilding", "worldbuilding_titles", "settings"):
        for item in _value_items(payload.get(key)):
            if isinstance(item, dict):
                item = item.get("title") or item.get("name") or item.get("entry_title")
            identity = _identity(item)
            if identity:
                titles.add(identity)
    return titles


def _searchable_fragments(value: Any) -> list[str]:
    fragments: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            fragments.extend(_searchable_fragments(item))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            fragments.extend(_searchable_fragments(item))
    elif value is not None:
        text = str(value).strip()
        if text:
            fragments.append(text)
    return fragments


def _worldbuilding_candidate_documents(items: list[Any]) -> dict[str, str]:
    documents: dict[str, str] = {}
    for item in items:
        if _candidate_status(item) == "rejected":
            continue
        if _candidate_type(item) not in {
            "worldbuilding_create",
            "worldbuilding_update",
            "worldbuilding_timeline",
        }:
            continue
        payload = _candidate_payload(item)
        title = _identity(
            payload.get("title")
            or payload.get("entry_title")
            or payload.get("name")
            or payload.get("target_name")
        )
        if not title:
            continue
        searchable = "\n".join(_searchable_fragments(payload))
        documents[title] = f"{documents.get(title, '')}\n{searchable}".strip()
    return documents


def _worldbuilding_term_is_covered(
    term: str,
    declared: set[str],
    documents: dict[str, str],
) -> bool:
    if not declared or not term:
        return False
    if term in declared:
        return True
    for declared_title in declared:
        document = documents.get(declared_title, "")
        # A provider may append a harmless category suffix when turning a fact
        # into a card title (游戏世界 -> 游戏世界设定).  Require containment in
        # the actual candidate title, not fuzzy edit-distance matching.
        if len(term) >= 2 and (term in declared_title or declared_title in term):
            return True
        # A narrower fact may be intentionally folded into a broader card
        # (灵气波动 -> 游戏世界设定).  Accept that only when the staged card's
        # persisted payload explicitly contains the fact term.
        if len(term) >= 2 and _contains_reference(document, term):
            return True
    return False


def _worldbuilding_expectation_terms(fact_type: str, payload: dict[str, Any]) -> set[str]:
    terms = _fact_worldbuilding_titles(payload)
    if fact_type == "worldbuilding_fact" and not terms:
        for key in ("title_hint", "title", "entry_title"):
            for item in _value_items(payload.get(key)):
                identity = _identity(item)
                if identity:
                    terms.add(identity)
    return terms


def _worldbuilding_term_is_grounded(
    term: str,
    fact_type: str,
    payload: dict[str, Any],
    chapter_content: str,
) -> bool:
    if _contains_reference(chapter_content, term):
        return True
    if fact_type != "worldbuilding_fact":
        return False
    for keyword in _value_items(payload.get("keywords")):
        text = str(keyword or "").strip()
        if len(_identity(text)) >= 2 and _contains_reference(chapter_content, text):
            return True
    return False


def _meaningful(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_meaningful(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_meaningful(item) for item in value)
    return bool(str(value or "").strip())


def _fact_has_character_profile_evidence(payload: dict[str, Any]) -> bool:
    """Identify facts that must update the stable character card."""
    return any(
        _meaningful(payload.get(key))
        for key in (
            "aliases",
            "role_hint",
            "appearance_clues",
            "background_clues",
            "ability_clues",
            "profile",
            "profile_clues",
            "tone_style",
            "catchphrases",
            "verbosity",
            "emotion_tendency",
            "custom_system_prompt",
        )
    )


def _fact_has_grounded_character_profile_evidence(
    payload: dict[str, Any],
    chapter_content: str,
) -> bool:
    if not _fact_has_character_profile_evidence(payload):
        return False
    for key in (
        "aliases",
        "role_hint",
        "appearance_clues",
        "background_clues",
        "ability_clues",
        "profile",
        "profile_clues",
        "tone_style",
        "catchphrases",
        "verbosity",
        "emotion_tendency",
        "custom_system_prompt",
    ):
        for fragment in _searchable_fragments(payload.get(key)):
            if len(_identity(fragment)) >= 2 and _contains_reference(chapter_content, fragment):
                return True
    return False


def _fact_relationship(payload: dict[str, Any], identity_map: dict[str, str]) -> str:
    source = _identity(
        payload.get("source_name")
        or payload.get("source")
        or payload.get("character_a")
    )
    target = _identity(
        payload.get("target_name")
        or payload.get("target")
        or payload.get("character_b")
    )
    relationship_type = _identity(
        payload.get("relationship_type")
        or payload.get("relation")
    )
    if not source or not target or not relationship_type:
        return ""
    return "|".join((
        identity_map.get(source, source),
        identity_map.get(target, target),
        relationship_type,
    ))


def _fact_relationship_is_grounded(payload: dict[str, Any], chapter_content: str) -> bool:
    source = str(
        payload.get("source_name")
        or payload.get("source")
        or payload.get("character_a")
        or ""
    )
    target = str(
        payload.get("target_name")
        or payload.get("target")
        or payload.get("character_b")
        or ""
    )
    return bool(
        source
        and target
        and _display_identity_references_content(source, chapter_content)
        and _display_identity_references_content(target, chapter_content)
    )


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


def _contains_reference(content: str, value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 2:
        return False
    if re.fullmatch(r"[A-Za-z0-9_. -]+", text):
        return bool(re.search(rf"(?<!\w){re.escape(text)}(?!\w)", content, re.IGNORECASE))
    return text in content


def _source_expectations(
    db: Session,
    project_id: str,
    items: list[Any],
    characters: list[Character],
    identity_map: dict[str, str],
    created_before: Any = None,
) -> tuple[set[str], set[str], set[str], set[str]]:
    expected_characters: set[str] = set()
    expected_worldbuilding: set[str] = set()
    expected_relationships: set[str] = set()
    expected_character_profiles: set[str] = set()
    run_id, chapter_id = _candidate_context(items)
    chapter_content = ""

    chapter = None
    if chapter_id:
        chapter = db.query(Chapter).filter(
            Chapter.id == chapter_id,
            Chapter.project_id == project_id,
        ).first()
    if chapter:
        chapter_content = str(chapter.content or "")
        alias_query = db.query(CharacterAlias).filter(CharacterAlias.project_id == project_id)
        if created_before is not None:
            alias_query = alias_query.filter(CharacterAlias.created_at <= created_before)
        aliases = alias_query.all()
        alias_by_character: dict[str, list[str]] = {}
        for alias in aliases:
            alias_by_character.setdefault(alias.character_id, []).append(str(alias.alias or ""))
        for character in characters:
            references = [str(character.name or ""), *alias_by_character.get(character.id, [])]
            if any(_contains_reference(chapter_content, reference) for reference in references):
                canonical = _identity(character.name)
                if canonical:
                    expected_characters.add(canonical)
        entry_query = db.query(WorldbuildingEntry).filter(
            WorldbuildingEntry.project_id == project_id,
        )
        if created_before is not None:
            entry_query = entry_query.filter(WorldbuildingEntry.created_at <= created_before)
        entries = entry_query.all()
        for entry in entries:
            if _contains_reference(chapter_content, str(entry.title or "")):
                title = _identity(entry.title)
                if title:
                    expected_worldbuilding.add(title)

    if run_id:
        for fact_type, payload in _source_fact_payloads(db, items):
            if fact_type in {"character_fact", "relationship_fact", "chapter_overview"}:
                fact_names = _grounded_fact_names(payload, identity_map, chapter_content)
                expected_characters.update(fact_names)
                if fact_type == "character_fact" and _fact_has_grounded_character_profile_evidence(
                    payload,
                    chapter_content,
                ):
                    expected_character_profiles.update(fact_names)
            if fact_type in {"worldbuilding_fact", "chapter_overview"}:
                expected_worldbuilding.update({
                    term
                    for term in _worldbuilding_expectation_terms(fact_type, payload)
                    if _worldbuilding_term_is_grounded(
                        term,
                        fact_type,
                        payload,
                        chapter_content,
                    )
                })
            if fact_type == "relationship_fact" and _fact_relationship_is_grounded(
                payload,
                chapter_content,
            ):
                relationship = _fact_relationship(payload, identity_map)
                if relationship:
                    expected_relationships.add(relationship)
    return (
        expected_characters,
        expected_worldbuilding,
        expected_relationships,
        expected_character_profiles,
    )


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

    run_id, _chapter_id = _candidate_context(items)
    run = (
        db.query(CatalogingChapterRun).filter(CatalogingChapterRun.id == run_id).first()
        if run_id
        else None
    )
    source_baseline = (run.started_at or run.created_at) if run is not None else None
    characters, existing, database_identity_map, by_id = _character_identity_index(
        db,
        project_id,
        created_before=source_baseline,
    )
    facts = _source_fact_payloads(db, items)
    identity_map = _candidate_character_identity_map(items, database_identity_map, by_id)
    identity_map = _apply_identity_hints(identity_map, facts)
    coverage = _canonicalize_coverage(coverage, identity_map)
    declared = set(coverage.declared_character_identities)
    profile_candidates = set(coverage.character_profile_candidate_identities)
    known_after_apply = existing | profile_candidates
    missing: list[str] = []
    review_warnings: list[str] = []

    new_without_profiles = sorted(declared - existing - profile_candidates)
    if new_without_profiles:
        missing.append(
            "character_create/update for new declared characters: "
            + "、".join(new_without_profiles)
        )

    relationship_endpoints = _relationship_endpoints(
        [
            *coverage.declared_relationship_identities,
            *coverage.relationship_candidate_identities,
        ]
    )
    unknown_relationship_endpoints = sorted(relationship_endpoints - known_after_apply)
    if unknown_relationship_endpoints:
        missing.append(
            "relationship endpoints without character profiles: "
            + "、".join(unknown_relationship_endpoints)
        )
    undeclared_relationship_endpoints = sorted(relationship_endpoints - declared)
    if undeclared_relationship_endpoints:
        missing.append(
            "relationship endpoints missing from coverage_manifest.characters: "
            + "、".join(undeclared_relationship_endpoints)
        )

    (
        expected_characters,
        expected_worldbuilding,
        expected_relationships,
        expected_character_profiles,
    ) = _source_expectations(
        db,
        project_id,
        items,
        characters,
        identity_map,
        source_baseline,
    )
    undeclared_source_characters = sorted(expected_characters - declared)
    if undeclared_source_characters:
        review_warnings.append(
            "source characters missing from coverage_manifest.characters: "
            + "、".join(undeclared_source_characters)
        )
    declared_worldbuilding = set(coverage.declared_worldbuilding_identities)
    worldbuilding_documents = _worldbuilding_candidate_documents(items)
    undeclared_source_worldbuilding = sorted({
        term
        for term in expected_worldbuilding
        if not _worldbuilding_term_is_covered(
            term,
            declared_worldbuilding,
            worldbuilding_documents,
        )
    })
    if undeclared_source_worldbuilding:
        review_warnings.append(
            "source worldbuilding missing from coverage_manifest.worldbuilding: "
            + "、".join(undeclared_source_worldbuilding)
        )
    undeclared_source_relationships = sorted(
        expected_relationships - set(coverage.declared_relationship_identities)
    )
    if undeclared_source_relationships:
        review_warnings.append(
            "source relationships missing from coverage_manifest.relationships: "
            + "、".join(undeclared_source_relationships)
        )
    undeclared_source_profiles = sorted(
        expected_character_profiles
        - set(coverage.declared_character_profile_identities)
    )
    if undeclared_source_profiles:
        review_warnings.append(
            "source character profile evidence missing from coverage_manifest.character_profiles: "
            + "、".join(undeclared_source_profiles)
        )

    if not missing and not review_warnings:
        return coverage
    return replace(
        coverage,
        persistence_missing=tuple(missing),
        review_warnings=tuple(review_warnings),
    )
