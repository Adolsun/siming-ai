"""Explicit entity bindings chosen by the cataloging Agent, never inferred from prose."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ...database.models import CatalogingCandidate, CatalogingChapterRun, Character, WorldbuildingEntry
from .candidate_io import candidate_payload


def plan_summary(db: Session, run: CatalogingChapterRun) -> dict[str, Any]:
    row = db.query(CatalogingCandidate).filter_by(
        chapter_run_id=run.id, item_type="chapter_summary",
    ).filter(CatalogingCandidate.status != "rejected").first()
    if row is None:
        raise ValueError("先提交 chapter_summary 建档计划，再提交该计划中的变更；历史事实不会自动绑定人物")
    return candidate_payload(row)


def bound_entity(db: Session, candidate: CatalogingCandidate, name: str, model: Any):
    """Use the current plan's selected ID, including when names are duplicated."""
    run = db.get(CatalogingChapterRun, candidate.chapter_run_id)
    if run is None or run.project_id != candidate.project_id:
        raise ValueError("建档候选的章节计划不存在或不属于当前作品")
    field = "character_bindings" if model is Character else "worldbuilding_bindings"
    binding = next((item for item in plan_summary(db, run).get(field, []) if item.get("name") == name), None)
    entity = db.get(model, binding["id"]) if binding else None
    if entity is None or entity.project_id != candidate.project_id:
        raise ValueError(f"计划中所选实体 {name!r} 尚未创建或已不存在")
    if model is WorldbuildingEntry and entity.status != "active":
        raise ValueError(f"计划中所选设定 {name!r} 已停用")
    return entity


def _bindings(db: Session, project_id: str, plan: dict, field: str, model: Any) -> dict[str, dict]:
    values = plan.get(field)
    if not isinstance(values, list):
        raise ValueError(f"chapter_summary.{field} 必须是数组；无实体时使用 []")
    result: dict[str, dict] = {}
    ids: set[str] = set()
    for index, item in enumerate(values):
        path = f"chapter_summary.{field}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{path} 必须是对象")
        name, identity, decision = item.get("name"), item.get("id"), item.get("decision")
        if not isinstance(name, str) or not name.strip() or name in result:
            raise ValueError(f"{path}.name 必须是唯一、非空的正式名称")
        try:
            if not isinstance(identity, str) or not identity or (decision == "new" and str(UUID(identity)) != identity):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError(f"{path}.id 必须是已有实体的真实 ID 或新实体的 client_id UUID") from None
        if identity in ids:
            raise ValueError(f"{path}.id 重复；同一实体只声明一次，临时称呼放在 source_labels")
        ids.add(identity)
        row = db.get(model, identity)
        if decision == "existing":
            if row is None or row.project_id != project_id:
                raise ValueError(f"{path}.id 不存在或不属于当前作品")
            actual = row.name if model is Character else row.title
            if actual != name:
                raise ValueError(f"{path}.name 与 id 对应的正式名称不同；当前名称为 {actual}")
            if model is WorldbuildingEntry and row.status != "active":
                raise ValueError(f"{path}.id 已停用")
        elif decision == "new":
            # Existence is checked again when the create is applied; replay of
            # an already applied run is handled by its persisted candidate IDs.
            if row is not None and (row.project_id != project_id or
                    (row.name if model is Character else row.title) != name):
                raise ValueError(f"{path}.id 已由另一实体占用")
        else:
            raise ValueError(f"{path}.decision 只能为 existing 或 new；未确定身份保留在叙述字段")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ValueError(f"{path}.reason 必须说明当前模型的身份判断依据")
        result[name] = item
    return result


def validate_plan_references(db: Session, project_id: str, run: CatalogingChapterRun,
                             normalized: dict[str, Any]) -> None:
    kind, payload = normalized["item_type"], normalized["payload"]
    plan = payload if kind == "chapter_summary" else plan_summary(db, run)
    characters = _bindings(db, project_id, plan, "character_bindings", Character)
    world = _bindings(db, project_id, plan, "worldbuilding_bindings", WorldbuildingEntry)

    def refs(values, bindings, path):
        for value in values or []:
            if not isinstance(value, str) or value not in bindings:
                raise ValueError(f"{path} 引用了计划中未绑定的实体 {value!r}；请由同一模型选择真实 ID，或仅在叙述中保留该称呼")

    if kind == "chapter_summary":
        manifest = payload.get("coverage_manifest") or {}
        refs(manifest.get("characters"), characters, "coverage_manifest.characters")
        refs(manifest.get("character_profiles"), characters, "coverage_manifest.character_profiles")
        refs(manifest.get("worldbuilding"), world, "coverage_manifest.worldbuilding")
        for relation in manifest.get("relationships") or []:
            refs([relation.get("source_name"), relation.get("target_name")], characters, "coverage_manifest.relationships")
        # Top-level characters/worldbuilding are entity lists too; arbitrary
        # participants and descriptions belong in summary_text/scenes.
        refs(payload.get("characters"), characters, "chapter_summary.characters")
        refs(payload.get("worldbuilding"), world, "chapter_summary.worldbuilding")
    elif kind.startswith("character_"):
        if kind == "character_relationship":
            refs([payload.get("source_name"), payload.get("target_name")], characters, kind)
        elif kind == "character_merge_candidate":
            refs([payload.get("primary_name"), payload.get("secondary_name")], characters, kind)
        else:
            identity = payload.get("id") or payload.get("client_id")
            binding = characters.get(payload.get("name"))
            if binding is None and identity:
                binding = next((v for v in characters.values() if v["id"] == identity), None)
            if binding is None or binding["id"] != identity:
                raise ValueError(f"{kind}.id/client_id 必须与 character_bindings 中模型选定的 ID 一致")
            if "name" in payload and payload["name"] != binding["name"]:
                raise ValueError(f"{kind}.name 必须与所选 ID 的正式名称一致；临时称呼放在 source_labels")
            if kind == "character_create" and binding["decision"] != "new":
                raise ValueError("已有角色必须使用 update，不能通过 create 覆盖")
    elif kind.startswith("worldbuilding_"):
        binding = world.get(payload.get("title"))
        if binding is None or binding["id"] != (payload.get("id") or payload.get("client_id")):
            raise ValueError(f"{kind}.id/client_id 必须与 worldbuilding_bindings 一致")
        if kind == "worldbuilding_create" and binding["decision"] != "new":
            raise ValueError("已有设定必须使用 update，不能通过 create 覆盖")
    elif kind == "chapter_link":
        refs([v.get("name") for v in payload.get("characters") or []], characters, "chapter_link.characters")
        refs(payload.get("worldbuilding_titles"), world, "chapter_link.worldbuilding_titles")
    elif kind in {"outline_create", "outline_update"}:
        from .outline_ops import validate_outline_target
        validate_outline_target(db, run.chapter, payload, create=kind == "outline_create")
        # Narrative participants may be anonymous. Only character_ids binds
        # a scene to a persistent character record.
        known = {v["id"] for v in characters.values()}
        if not set(payload.get("character_ids") or []).issubset(known):
            raise ValueError("outline.character_ids 必须来自本计划 character_bindings")
