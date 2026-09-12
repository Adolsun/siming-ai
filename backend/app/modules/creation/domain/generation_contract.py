"""Shared, deterministic contracts for model-generated creation entities."""

from __future__ import annotations

import json
from typing import Any

from .entity_contract import (
    ENTITY_OUTPUT_CONTRACTS,
    PLACE_ENTITY_DIMENSIONS,
    REQUIRED_STAGE_TEXT_FIELDS,
)
from .generation_errors import (
    CREATION_GENERATION_DETAILS as CREATION_GENERATION_DETAILS,
)
from .generation_errors import (
    CreationGenerationError as CreationGenerationError,
)
from .opening_outline_contract import validate_opening_outline

ENTITY_GENERATION_INSTRUCTION = (
    "\n目标实体输出契约：{contract}\n"
    "目标模式：{mode}。目标对象放入 data 内 field 指定的数组，"
    "每个对象必须逐字段满足 required_values；不得用 type 或 entity_type 代替 dimension。"
    "existing 模式恰好返回一个对象；new 模式按作者要求生成新对象。"
    "\ninitialize_stage={initialize_stage}：为 true 时，本阶段尚无资料，"
    "必须同时返回阶段契约要求的全部顶层字段，作为首版资料；"
    "为 false 时，只修改目标实体，既有阶段的其他字段保持原样。"
)


def entity_generation_instruction(target: dict[str, Any] | None) -> str:
    if not target:
        return ""
    contract = ENTITY_OUTPUT_CONTRACTS[str(target["entity_type"])]
    return ENTITY_GENERATION_INSTRUCTION.format(
        contract=json.dumps(contract, ensure_ascii=False),
        mode=target["mode"],
        initialize_stage=json.dumps(bool(target.get("initialize_stage"))),
    )


def validate_stage_text_fields(stage: str, data: dict[str, Any]) -> None:
    for field in REQUIRED_STAGE_TEXT_FIELDS.get(stage, ()):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CreationGenerationError(
                "creation_generated_stage_fields_missing",
                f"$.data.{field}",
            )


def validate_generated_entity(
    stage: str,
    data: dict[str, Any],
    target: dict[str, Any] | None,
    *,
    volume_index: list[dict[str, Any]] | None = None,
    character_index: list[dict[str, Any]] | None = None,
) -> None:
    """Validate model structure before normalization can merge any old data."""
    if not target or target.get("initialize_stage"):
        validate_stage_text_fields(stage, data)
    if target:
        contract = ENTITY_OUTPUT_CONTRACTS[str(target["entity_type"])]
        field = str(contract["field"])
        rows = data.get(field)
        path = f"$.data.{field}"
        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
            raise CreationGenerationError("creation_generated_collection_invalid", path)
        if target.get("mode") == "existing" and len(rows) != 1:
            raise CreationGenerationError("creation_generated_count_invalid", path)
        required = contract["required_values"]
        for index, row in enumerate(rows):
            for name, value in required.items():
                if row.get(name) != value:
                    raise CreationGenerationError(
                        "creation_generated_dimension_invalid", f"{path}[{index}].{name}"
                    )
    if stage == "opening_outline":
        validate_opening_outline(
            data,
            volume_index=volume_index,
            character_index=character_index,
            partial=bool(target and not target.get("initialize_stage")),
        )
    if stage == "locations":
        entries = data.get("entries")
        if isinstance(entries, list):
            for index, row in enumerate(entries):
                if (
                    isinstance(row, dict)
                    and row.get("dimension") not in PLACE_ENTITY_DIMENSIONS.values()
                ):
                    raise CreationGenerationError(
                        "creation_generated_dimension_invalid",
                        f"$.data.entries[{index}].dimension",
                    )
