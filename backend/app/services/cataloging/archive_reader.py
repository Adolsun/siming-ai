"""Project-scoped, paginated archive reads for every cataloging transport."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ...database.models import Character, WorldbuildingEntry, OutlineNode, CharacterRelationship
from .snapshots import character_snapshot, worldbuilding_snapshot


async def read_cataloging_archive(db: Session, project_id: str, args: dict[str, Any]) -> dict:
    kind = args.get("kind")
    model = {"character": Character, "worldbuilding": WorldbuildingEntry,
             "outline": OutlineNode, "relationship": CharacterRelationship}.get(kind)
    if model is None:
        raise ValueError("kind 必须为 character、worldbuilding、outline 或 relationship")
    ids = args.get("ids") or []
    cursor, limit = args.get("cursor", 0), args.get("limit", 20)
    if not isinstance(cursor, int) or cursor < 0 or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("cursor 必须非负，limit 必须为 1..50")
    if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids) or len(ids) > 5:
        raise ValueError("ids 必须是至多 5 个真实 ID 的数组；省略时读取索引")
    query = db.query(model).filter(model.project_id == project_id)
    if kind == "worldbuilding":
        query = query.filter(model.status == "active")
    if ids:
        rows = query.filter(model.id.in_(ids)).all()
        if {row.id for row in rows} != set(ids):
            raise ValueError("部分 ID 不存在、不属于当前作品或已停用")
        result = []
        for row in rows:
            if kind == "character":
                data = character_snapshot(row)
            elif kind == "worldbuilding":
                data = worldbuilding_snapshot(row)
            else:
                data = {column.name: getattr(row, column.name) for column in model.__table__.columns
                        if column.name not in {"created_at", "updated_at"}}
            result.append({"id": row.id, **data})
        return {"tool": "read_cataloging_archive", "status": "ok", "data": {"items": result, "has_more": False}}
    rows = query.order_by(model.id).offset(cursor).limit(limit + 1).all()
    items = []
    for row in rows[:limit]:
        fields = ("name", "role_type") if kind == "character" else ("title", "dimension", "node_type", "parent_id")
        if kind == "relationship":
            fields = ("character_a_id", "character_b_id", "relationship_type")
        items.append({"id": row.id, **{key: getattr(row, key) for key in fields if hasattr(row, key)}})
    more = len(rows) > limit
    return {"tool": "read_cataloging_archive", "status": "ok", "data": {
        "items": items, "has_more": more, "next_arguments": {"kind": kind, "cursor": cursor + limit, "limit": limit} if more else None}}
