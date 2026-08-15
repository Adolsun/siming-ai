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


def test_creation_stage_mcp_contract_declares_conditional_model_requirement():
    spec = registry.get_spec("generate_novel_creation_stage")
    assert spec is not None

    schema = spec.mcp_schema()["inputSchema"]
    model_schema = schema["properties"]["model"]
    assert "Required when stage or artifact is concepts or all" in model_schema["description"]
    assert "external MCP client is not inherited" in model_schema["description"]
    assert schema["allOf"] == [
        {
            "if": {
                "properties": {"stage": {"enum": ["all", "concepts"]}},
                "required": ["stage"],
            },
            "then": {
                "properties": {
                    "model": {"minLength": 1},
                    "use_model": {"const": True},
                },
                "required": ["model"],
            },
        },
    ]


@pytest.mark.parametrize("stage", ["concepts", "all"])
def test_creation_stage_contract_rejects_missing_model_when_runtime_requires_it(stage):
    spec = registry.get_spec("generate_novel_creation_stage")
    assert spec is not None

    with pytest.raises(ValidationError, match="model is required"):
        spec.validate_input({"session_id": "session-1", "stage": stage})

    validated = spec.validate_input(
        {"session_id": "session-1", "stage": stage, "model": "codex_cli:codex-cli"}
    )
    assert validated.model == "codex_cli:codex-cli"


@pytest.mark.parametrize("stage", ["concepts", "all"])
def test_creation_stage_contract_rejects_disabling_model_when_runtime_requires_it(stage):
    spec = registry.get_spec("generate_novel_creation_stage")
    assert spec is not None

    with pytest.raises(ValidationError, match="use_model must be true"):
        spec.validate_input(
            {
                "session_id": "session-1",
                "stage": stage,
                "model": "codex_cli:codex-cli",
                "use_model": False,
            }
        )


def test_creation_stage_contract_keeps_model_optional_for_deterministic_stages():
    spec = registry.get_spec("generate_novel_creation_stage")
    assert spec is not None

    validated = spec.validate_input(
        {"session_id": "session-1", "stage": "world_style", "use_model": False}
    )
    assert validated.model == ""


@pytest.mark.parametrize(
    ("tool_name", "artifact"),
    [
        ("generate_creation_artifact", "concepts"),
        ("generate_creation_artifact", "all"),
        ("refine_creation_artifact", "concepts"),
        ("refine_creation_artifact", "all"),
        ("regenerate_creation_artifact", "concepts"),
        ("regenerate_creation_artifact", "all"),
    ],
)
def test_artifact_generation_contracts_apply_the_same_model_rule(tool_name, artifact):
    spec = registry.get_spec(tool_name)
    assert spec is not None
    arguments = {
        "session_id": "session-1",
        "artifact": artifact,
        "expected_revision": 3,
    }
    if tool_name == "refine_creation_artifact":
        arguments["instruction"] = "调整核心冲突"

    with pytest.raises(ValidationError, match="model is required"):
        spec.validate_input(arguments)

    arguments["model"] = "codex_cli:codex-cli"
    assert spec.validate_input(arguments).model == "codex_cli:codex-cli"


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
