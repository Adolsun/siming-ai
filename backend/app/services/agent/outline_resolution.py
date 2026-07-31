"""Resolve a workspace chapter outline from explicit UI and text targets."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...core.numbers import extract_chapter_number
from ...database.models import OutlineNode
from ..workspace.utils import normalize_outline_lookup


def resolve_outline_node_id(
    db: Session,
    project_id: str,
    chapter_number: int | None,
    outline_query: str,
    selected_outline_node_id: str | None = None,
) -> str:
    """Resolve by selected node, chapter number, then normalized title."""
    if selected_outline_node_id:
        selected = db.query(OutlineNode).filter(
            OutlineNode.id == selected_outline_node_id,
            OutlineNode.project_id == project_id,
            OutlineNode.node_type == "chapter",
        ).first()
        if selected:
            return selected.id

    nodes = db.query(OutlineNode).filter(
        OutlineNode.project_id == project_id,
        OutlineNode.node_type == "chapter",
    ).order_by(OutlineNode.sort_order.asc(), OutlineNode.created_at.asc()).all()

    resolved_chapter_number = chapter_number or extract_chapter_number(outline_query)
    if resolved_chapter_number is not None:
        for node in nodes:
            if extract_chapter_number(node.title or "", allow_bare=True) == resolved_chapter_number:
                return node.id

    query = str(outline_query or "").strip()
    normalized_query = normalize_outline_lookup(query)
    if query:
        for node in nodes:
            if node.id == query or node.title == query:
                return node.id
        if normalized_query:
            for node in nodes:
                if normalize_outline_lookup(node.title) == normalized_query:
                    return node.id
            for node in nodes:
                normalized_title = normalize_outline_lookup(node.title)
                if normalized_title and (
                    normalized_query in normalized_title or normalized_title in normalized_query
                ):
                    return node.id
    return ""


__all__ = ["resolve_outline_node_id"]
