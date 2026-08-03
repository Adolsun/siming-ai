"""Deterministic dependency graph and consistency checks for creation sessions."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from app.database.models import NovelCreationSession
from app.services.novel_creation_contract import (
    IMPACT_DEPENDENCIES,
    SOFT_DEPENDENCIES,
    STAGE_LABELS,
    STAGE_ORDER,
)
from app.services.novel_creation_entities import list_creation_entities


def _text(value: Any) -> str:
    return str(value or "").strip()


def _references(row: dict[str, Any], pairs: tuple[tuple[str, str], ...]) -> list[str]:
    values: list[str] = []
    for left, right in pairs:
        for field in (left, right):
            value = _text(row.get(field))
            if value and value not in values:
                values.append(value)
    return values


def creation_dependency_graph(session: NovelCreationSession) -> dict[str, Any]:
    """Return one graph covering artifact and projected entity dependencies."""
    draft = session.draft_json if isinstance(session.draft_json, dict) else {}
    stages = draft.get("stages") if isinstance(draft.get("stages"), dict) else {}
    entities = list_creation_entities(session)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for stage in STAGE_ORDER:
        state = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
        nodes.append({
            "id": f"artifact:{stage}",
            "kind": "artifact",
            "artifact": stage,
            "label": STAGE_LABELS[stage],
            "status": _text(state.get("status")) or "pending",
        })
        for dependency in SOFT_DEPENDENCIES.get(stage, ()):
            edges.append({
                "source": f"artifact:{dependency}",
                "target": f"artifact:{stage}",
                "relation": "soft",
            })
        for target in IMPACT_DEPENDENCIES.get(stage, ()):
            edges.append({
                "source": f"artifact:{stage}",
                "target": f"artifact:{target}",
                "relation": "impact",
            })

    by_type: dict[str, list[dict[str, Any]]] = {}
    by_name: dict[tuple[str, str], str] = {}
    for item in entities:
        by_type.setdefault(item["entity_type"], []).append(item)
        label = _text(item["data"].get("name") or item["data"].get("title") or item["entity_key"])
        nodes.append({
            "id": f"entity:{item['id']}",
            "kind": "entity",
            "artifact": item["artifact"],
            "entity_type": item["entity_type"],
            "label": label,
            "status": item["status"],
        })
        if label:
            by_name[(item["entity_type"], label)] = item["id"]
        edges.append({
            "source": f"artifact:{item['artifact']}",
            "target": f"entity:{item['id']}",
            "relation": "contains",
        })

    for relation_type, target_types, fields in (
        ("relationship", ("character",), (("character_a", "character_b"), ("source", "target"))),
        (
            "world_relation",
            ("location", "faction"),
            (("source_title", "target_title"), ("source", "target")),
        ),
    ):
        for relation in by_type.get(relation_type, []):
            for reference in _references(relation["data"], fields):
                target_id = next(
                    (
                        by_name.get((target_type, reference))
                        for target_type in target_types
                        if by_name.get((target_type, reference))
                    ),
                    None,
                )
                if target_id:
                    edges.append({
                        "source": f"entity:{relation['id']}",
                        "target": f"entity:{target_id}",
                        "relation": "references",
                    })

    chapter_by_key: dict[str, str] = {}
    for item in by_type.get("chapter_outline", []):
        for key in (
            item["data"].get("id"),
            item["data"].get("client_id"),
            item["data"].get("title"),
        ):
            if _text(key):
                chapter_by_key[_text(key)] = item["id"]
    for scene in by_type.get("scene_outline", []):
        parent = _text(scene["data"].get("parent_client_id") or scene["data"].get("chapter_id"))
        if parent in chapter_by_key:
            edges.append({
                "source": f"entity:{scene['id']}",
                "target": f"entity:{chapter_by_key[parent]}",
                "relation": "belongs_to",
            })

    return {
        "session_id": session.id,
        "revision": int(session.revision or 0),
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "artifact_count": len(STAGE_ORDER),
            "entity_count": len(entities),
            "edge_count": len(edges),
        },
    }


def validate_creation_consistency(session: NovelCreationSession) -> dict[str, Any]:
    """Validate referential and workflow consistency without changing author data."""
    graph = creation_dependency_graph(session)
    entities = list_creation_entities(session)
    issues: list[dict[str, Any]] = []
    by_type: dict[str, list[dict[str, Any]]] = {}
    for item in entities:
        by_type.setdefault(item["entity_type"], []).append(item)

    for entity_type, rows in by_type.items():
        labels = [_text(row["data"].get("name") or row["data"].get("title")) for row in rows]
        for label, count in Counter(value for value in labels if value).items():
            if count > 1:
                issues.append({
                    "code": "duplicate_entity_label",
                    "severity": "warning",
                    "entity_type": entity_type,
                    "label": label,
                    "message": f"{entity_type} 中有 {count} 个同名对象“{label}”",
                })

    names = {
        entity_type: {_text(row["data"].get("name") or row["data"].get("title")) for row in rows}
        for entity_type, rows in by_type.items()
    }
    for relation_type, target_types, fields in (
        ("relationship", ("character",), (("character_a", "character_b"), ("source", "target"))),
        (
            "world_relation",
            ("location", "faction"),
            (("source_title", "target_title"), ("source", "target")),
        ),
    ):
        known = set().union(*(names.get(target_type, set()) for target_type in target_types))
        for relation in by_type.get(relation_type, []):
            for reference in _references(relation["data"], fields):
                if reference not in known:
                    issues.append({
                        "code": "dangling_entity_reference",
                        "severity": "error",
                        "entity_id": relation["id"],
                        "reference": reference,
                        "message": f"{relation_type} 引用了不存在的对象“{reference}”",
                    })

    chapter_keys = {
        _text(value)
        for row in by_type.get("chapter_outline", [])
        for value in (row["data"].get("id"), row["data"].get("client_id"), row["data"].get("title"))
        if _text(value)
    }
    for scene in by_type.get("scene_outline", []):
        parent = _text(scene["data"].get("parent_client_id") or scene["data"].get("chapter_id"))
        if parent and parent not in chapter_keys:
            issues.append({
                "code": "orphan_scene_outline",
                "severity": "error",
                "entity_id": scene["id"],
                "reference": parent,
                "message": f"场景细纲找不到所属章节“{parent}”",
            })

    draft = session.draft_json if isinstance(session.draft_json, dict) else {}
    stages = draft.get("stages") if isinstance(draft.get("stages"), dict) else {}
    for stage in STAGE_ORDER:
        state = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
        if state.get("status") == "stale":
            issues.append({
                "code": "stale_artifact",
                "severity": "warning",
                "artifact": stage,
                "message": f"{STAGE_LABELS[stage]}基于旧版上游数据，建议重新校验",
            })

    blocking = sum(1 for item in issues if item["severity"] == "error")
    warnings = len(issues) - blocking
    return {
        "session_id": session.id,
        "revision": int(session.revision or 0),
        "valid": blocking == 0,
        "issues": deepcopy(issues),
        "summary": {"blocking": blocking, "warnings": warnings, "total": len(issues)},
        "graph": graph,
    }


__all__ = ["creation_dependency_graph", "validate_creation_consistency"]
