"""Assemble validated creation entities for their one-time project materialization."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.database.models import NovelCreationSession
from app.services.novel_creation_contract import SCHEMA_VERSION
from app.services.novel_creation_workspace import (
    _dict,
    _list,
    _rule_lines,
    _selected_project_seed,
    _text,
    derive_stage,
    initialize_session_draft,
)


def build_project_materialization_payload(session: NovelCreationSession) -> dict[str, Any]:
    project_payload = _selected_project_seed(session)
    draft = deepcopy(initialize_session_draft(session))
    stages = draft.get("stages", {})
    final = derive_stage(session, "final_review", draft)
    characters = _dict(stages.get("characters", {}).get("data")) or derive_stage(session, "characters")
    world = _dict(stages.get("world_style", {}).get("data")) or derive_stage(session, "world_style")
    locations = _dict(stages.get("locations", {}).get("data")) or derive_stage(session, "locations")
    opening_state = _dict(stages.get("opening_outline"))
    opening = _dict(opening_state.get("data")) if opening_state.get("status") == "confirmed" else {}
    from app.modules.creation.domain.opening_outline_contract import (
        normalize_opening_outline,
        validate_opening_outline,
    )
    from app.services.novel_creation_entities import creation_character_index, creation_volume_index

    volume_index = creation_volume_index(session)
    if opening_state.get("status") == "confirmed":
        validate_opening_outline(opening, volume_index=volume_index, character_index=creation_character_index(session))
        opening = normalize_opening_outline(opening)
    volumes = [
        {**deepcopy(entity.data_json), "creation_entity_id": entity.id}
        for entity in sorted(session.entities, key=lambda row: int(row.position or 0))
        if entity.artifact_key == "macro_outline" and entity.entity_type == "volume" and entity.status == "active"
    ]
    character_rows = [
        {**deepcopy(entity.data_json), "creation_entity_id": entity.id}
        for entity in sorted(session.entities, key=lambda row: int(row.position or 0))
        if entity.artifact_key == "characters" and entity.entity_type == "character" and entity.status == "active"
    ]
    protagonist = next((row for row in character_rows if row.get("role_type") == "protagonist"), character_rows[0] if character_rows else {})
    supporting = [row for row in character_rows if row is not protagonist]
    all_world = _list(world.get("worldbuilding"))
    known_titles = {_text(item.get("title")) for item in all_world if isinstance(item, dict)}
    all_world.extend(item for item in _list(locations.get("entries")) if isinstance(item, dict) and _text(item.get("title")) not in known_titles)
    project_payload.update({
        "protagonist": protagonist,
        "characters": supporting,
        "relationships": _list(characters.get("relationships")),
        "writing_style": _text(world.get("writing_style") or project_payload.get("writing_style")),
        "world_tone": _text(world.get("world_tone") or project_payload.get("world_tone")),
        "story_structure": _text(world.get("story_structure") or project_payload.get("story_structure")),
        "pacing": _text(world.get("pacing") or project_payload.get("pacing")),
        "style_rules": _rule_lines(world.get("style_rules", project_payload.get("style_rules"))),
        "forbidden_patterns": _rule_lines(world.get("forbidden_patterns", project_payload.get("forbidden_patterns"))),
        "worldbuilding": all_world,
        "worldbuilding_relations": _list(locations.get("relations")),
        "volume_outline": volumes,
        "outline": _list(opening.get("chapters")) + _list(opening.get("sections")),
        "apply_warnings": _list(final.get("warnings")),
        "novel_creation_schema_version": SCHEMA_VERSION,
    })
    return project_payload
