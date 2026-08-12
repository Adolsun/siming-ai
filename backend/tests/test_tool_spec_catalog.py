"""Typed workspace tool catalog compatibility tests."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.architecture.tool_spec import LegacyToolInput
from app.modules.creation.interfaces.tool_definitions import (
    TOOL_DEFINITIONS as CREATION_TOOL_DEFINITIONS,
)
from app.services.workspace.registry import registry


def _openai_parameters(name: str) -> dict:
    schema = next(
        item for item in registry.get_schemas() if item["function"]["name"] == name
    )
    return schema["function"]["parameters"]


def test_creation_tool_schema_has_one_typed_source():
    spec = registry.get_spec("generate_novel_creation_stage")
    assert spec is not None
    assert spec.version == "3.0.0"
    assert _openai_parameters(spec.name) == spec.parameters_schema()
    assert spec.mcp_schema()["inputSchema"] == spec.parameters_schema()
    assert spec.frontend_metadata()["version"] == spec.version
    assert {"session_id", "stage"}.issubset(
        set(spec.parameters_schema().get("required", []))
    )


def test_every_creation_session_tool_has_a_typed_input_contract():
    unrelated_generators = {
        "design_plot",
        "chapter_writer",
        "character_writer",
        "outline_writer",
        "worldbuilding_writer",
        "rewrite_text",
        "expand_text",
        "continue_text",
        "roleplay_character",
        "dialogue_battle",
    }

    for definition in CREATION_TOOL_DEFINITIONS:
        if definition.name in unrelated_generators:
            continue
        spec = registry.get_spec(definition.name)
        assert spec is not None
        assert spec.input_model is not LegacyToolInput, definition.name
        assert spec.version == "3.0.0"


def test_creation_import_contract_rejects_unknown_strategy_and_artifact():
    spec = registry.get_spec("apply_creation_import")
    assert spec is not None

    with pytest.raises(ValidationError):
        spec.validate_input(
            {
                "import_id": "import-1",
                "selected_artifacts": ["unknown"],
                "strategy": "replace_everything",
                "expected_revision": 3,
            }
        )


def test_creation_operation_contract_requires_operation_id():
    spec = registry.get_spec("cancel_creation_operation")
    assert spec is not None
    with pytest.raises(ValidationError):
        spec.validate_input({})


def test_unmigrated_tool_keeps_legacy_schema_projection():
    tool = registry.get("list_projects")
    spec = registry.get_spec("list_projects")
    assert tool is not None and spec is not None
    schema = spec.parameters_schema()
    assert schema["properties"] == tool.input_schema
    assert schema.get("required", []) == tool.required


def test_frontend_catalog_comes_from_tool_specs():
    metadata = {
        item["name"]: item for item in registry.list_for_frontend()
    }["inspect_story_granularity"]
    assert metadata["version"] == "3.0.0"
    assert metadata["writes_project_data"] is False
