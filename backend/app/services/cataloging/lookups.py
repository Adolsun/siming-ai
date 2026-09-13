"""Local lookup helpers for cataloging.

These helpers intentionally avoid importing workspace assistant packages, so the
cataloging pipeline can be imported without optional web-search dependencies.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from ...database.models import Character, OutlineNode, WorldbuildingEntry
from ...database.query_filters import current_worldbuilding_clause


def find_character_by_name_or_id(db: Session, project_id: str, value: Any) -> Character | None:
    text = str(value or "").strip()
    rows = db.query(Character).filter(Character.project_id == project_id,
        (Character.id == text) | (Character.name == text)).all()
    if len(rows) > 1:
        raise ValueError("角色引用不唯一；请由模型选择真实 ID")
    return rows[0] if rows else None





def find_worldbuilding_by_title_or_id(
    db: Session,
    project_id: str,
    value: Any,
) -> WorldbuildingEntry | None:
    text = str(value or "").strip()
    if not text:
        return None
    by_id = (
        db.query(WorldbuildingEntry)
        .filter(
            WorldbuildingEntry.project_id == project_id,
            WorldbuildingEntry.id == text,
        )
        .first()
    )
    if by_id and str(by_id.status or "active").strip().lower() == "active":
        return by_id
    current = db.query(WorldbuildingEntry).filter(
        WorldbuildingEntry.project_id == project_id,
        current_worldbuilding_clause(WorldbuildingEntry.status),
    )
    exact = current.filter(WorldbuildingEntry.title == text).first()
    if exact:
        return exact
    return None




def next_outline_sort_order(db: Session, project_id: str, parent_id: str | None) -> int:
    last = (
        db.query(OutlineNode)
        .filter(OutlineNode.project_id == project_id, OutlineNode.parent_id == parent_id)
        .order_by(OutlineNode.sort_order.desc(), OutlineNode.created_at.desc())
        .first()
    )
    return (last.sort_order + 1) if last and last.sort_order is not None else 0


def next_worldbuilding_sort_order(db: Session, project_id: str, dimension: str) -> int:
    last = (
        db.query(WorldbuildingEntry)
        .filter(WorldbuildingEntry.project_id == project_id, WorldbuildingEntry.dimension == dimension)
        .order_by(WorldbuildingEntry.sort_order.desc(), WorldbuildingEntry.created_at.desc())
        .first()
    )
    return (last.sort_order + 1) if last and last.sort_order is not None else 0


def normalize_lookup(value: str) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s:：，,。.!！?？（）()\[\]【】《》<>\"'“”‘’-]+", "", text)
