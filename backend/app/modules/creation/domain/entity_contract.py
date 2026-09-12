"""Authoritative creation entity types and deterministic reference diagnostics."""
from __future__ import annotations

ENTITY_COLLECTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "world_style": (("worldbuilding", "worldbuilding"),),
    "characters": (("characters", "character"), ("relationships", "relationship")),
    "locations": (("entries", "place"), ("relations", "world_relation")),
    "macro_outline": (("volumes", "volume"),),
    "opening_outline": (("chapters", "chapter_outline"), ("sections", "scene_outline")),
}
PLACE_ENTITY_DIMENSIONS = {"location": "geography", "faction": "factions"}
REQUIRED_STAGE_TEXT_FIELDS = {
    "macro_outline": ("story_overview", "core_conflict", "ending_direction"),
}
ENTITY_OUTPUT_CONTRACTS = {
    entity_type: {
        "artifact": artifact,
        "field": field,
        "required_values": (
            {"dimension": PLACE_ENTITY_DIMENSIONS[entity_type]} if kind == "place" else {}
        ),
    }
    for artifact, collections in ENTITY_COLLECTIONS.items()
    for field, kind in collections
    for entity_type in (PLACE_ENTITY_DIMENSIONS if kind == "place" else (kind,))
}
ENTITY_TYPES_BY_ARTIFACT: dict[str, frozenset[str]] = {
    artifact: frozenset(
        entity_type for entity_type, contract in ENTITY_OUTPUT_CONTRACTS.items()
        if contract["artifact"] == artifact
    )
    for artifact in ENTITY_COLLECTIONS
}
CREATION_REFERENCE_DETAILS = {
    "creation_context_entity_unavailable": (
        "context_entity_ids 引用的实体不存在、已删除或不属于当前立项会话。"
        "本次未启动生成、未写入。请先用 list_creation_entities 检索当前实体，"
        "再用 get_creation_entity 读取有效 ID，修正引用后再调用；不要原样重试。"
    ),
    "creation_target_entity_unavailable": (
        "entity_id 指定的目标实体不存在、已删除或不属于当前立项会话。"
        "本次未启动生成、未写入。请用 list_creation_entities 重新选择并读取真实实体 ID。"
    ),
    "creation_target_artifact_mismatch": (
        "entity_id 指定的实体不属于 artifact 对象。本次未写入；请读取目标实体后修正 artifact。"
    ),
    "creation_entity_type_invalid": (
        "目标实体类型 entity_type 不属于当前 artifact。请按工具 Schema 中的类型填写；"
        "characters 阶段的角色类型为 character，关系类型为 relationship。本次未启动生成、未写入。"
    ),
    "creation_context_artifact_invalid": (
        "context_artifacts 含无效的立项对象名称。本次未启动生成、未写入；"
        "请用 get_creation_snapshot 读取当前对象名称并修正该字段。"
    ),
    "creation_entity_identity_conflict": (
        "修改后的实体标识与另一个已有或已删除实体冲突，本次未写入。"
        "请先用 list_creation_entities 核对两个对象，不能通过改名替换另一个实体。"
    ),
}


class CreationReferenceError(ValueError):
    """A repository-owned reference rejection, safe to persist and show to a model."""

    def __init__(self, reason: str, path: str):
        super().__init__(CREATION_REFERENCE_DETAILS[reason])
        self.reason = reason
        self.path = path

    def tool_result(self, tool: str) -> dict:
        return {"tool": tool, "status": "error", "detail": str(self), "data": {
            "reason": self.reason, "path": self.path, "retryable": True,
        }}
