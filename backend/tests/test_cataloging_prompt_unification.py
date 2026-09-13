"""API, CLI and MCP expose one schema and one planning workflow."""
import json
from app.prompts.cataloging_source import (get_internal_cataloging_system_prompt,
    get_external_cataloging_system_prompt, get_cataloging_candidate_schema)
from app.modules.continuity.domain.candidate_contract import candidate_record_schema
from app.services.workspace.registry import registry


def test_candidate_prompt_is_generated_from_the_exported_tool_schema():
    prompt_schema = json.loads(get_cataloging_candidate_schema().split("\n", 1)[1])
    tool_schema = registry.get_spec("save_external_cataloging_candidates").parameters_schema()
    assert prompt_schema == candidate_record_schema()
    assert tool_schema["properties"]["candidates"]["items"] == prompt_schema


def test_all_entrypoints_use_the_same_plan_rules():
    internal = get_internal_cataloging_system_prompt()
    external = get_external_cataloging_system_prompt()
    assert internal in external
    for text in (internal, external):
        assert "character_bindings" in text and "worldbuilding_bindings" in text
        assert "finalize" in text and "set_tool_categories" in text
        assert "只输出 JSONL" not in text
    assert registry.get("save_external_cataloging_facts") is None
    names = {tool.name for tool in registry.list_for_mcp(permission_pack="cataloging_worker", categories=["cataloging"])}
    assert {"read_cataloging_archive", "get_next_external_cataloging_chapter", "save_external_cataloging_candidates"} <= names


def test_public_prompt_pack_cannot_reintroduce_an_earlier_decision_phase():
    from app.services.prompt_packs.seed import BUILTIN_PACKS
    from app.prompts.cataloging_source import get_project_binding_rules, get_external_no_api_rules
    pack = next(pack for pack in BUILTIN_PACKS if pack["pack_id"] == "cataloging_external_no_api")
    text = pack["system_prompt"]
    for rules in (get_internal_cataloging_system_prompt(), get_project_binding_rules(), get_external_no_api_rules()):
        assert rules in text
    assert "save_external_cataloging_facts" not in text
    assert "facts → candidates" not in text
