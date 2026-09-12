"""Shared, deterministic contracts for model-generated creation entities."""

from __future__ import annotations

import json
from typing import Any

from .entity_contract import (
    ENTITY_OUTPUT_CONTRACTS,
    PLACE_ENTITY_DIMENSIONS,
    REQUIRED_STAGE_TEXT_FIELDS,
)
from .opening_outline_contract import OPENING_OUTLINE_DETAILS, validate_opening_outline

ENTITY_GENERATION_INSTRUCTION = (
    "\n目标实体输出契约：{contract}\n"
    "目标模式：{mode}。目标对象放入 data 内 field 指定的数组，"
    "每个对象必须逐字段满足 required_values；不得用 type 或 entity_type 代替 dimension。"
    "existing 模式恰好返回一个对象；new 模式按作者要求生成新对象。"
    "\ninitialize_stage={initialize_stage}：为 true 时，本阶段尚无资料，"
    "必须同时返回阶段契约要求的全部顶层字段，作为首版资料；"
    "为 false 时，只修改目标实体，既有阶段的其他字段保持原样。"
)
CREATION_GENERATION_DETAILS = {
    **OPENING_OUTLINE_DETAILS,
    "creation_generated_collection_invalid": (
        "模型没有在目标阶段的原生集合中返回非空对象数组。"
        "请按目标实体输出契约将对象放入 data 内 field 指定的数组；本次生成未写入。"
    ),
    "creation_generated_dimension_invalid": (
        "生成条目的 dimension 不符合目标类型：地点 location 必须为 geography，"
        "势力 faction 必须为 factions；仅写 type 或 entity_type 不能代替 dimension。"
        "请按此结构修正生成要求后再调用；本次生成未写入。"
    ),
    "creation_generated_count_invalid": (
        "指定既有实体的修订必须恰好返回一个目标对象；本次生成未写入。"
    ),
    "creation_generated_stage_fields_missing": (
        "全书主线与卷纲必须同时包含非空字符串 story_overview、core_conflict、"
        "ending_direction，以及 volumes 分卷规划。首次生成卷实体时也必须返回这些顶层字段。"
        "请按此契约修正模型输出；本阶段生成结果未写入。"
    ),
}


class CreationGenerationError(ValueError):
    """A schema failure with repository-owned text, never provider exception text."""

    failure_class = "invalid_model_output"

    def __init__(self, reason: str, path: str, *, attempt: int = 1):
        super().__init__(f"{path}：{CREATION_GENERATION_DETAILS[reason]}")
        self.reason = reason
        self.path = path
        self.attempt = attempt

    def tool_result(self, tool: str) -> dict[str, Any]:
        return {
            "tool": tool,
            "status": "error",
            "detail": CREATION_GENERATION_DETAILS[self.reason],
            "data": {
                "reason": self.reason,
                "path": self.path,
                "retryable": True,
            },
        }


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
        validate_opening_outline(data, volume_index=volume_index, partial=bool(target and not target.get("initialize_stage")))
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
