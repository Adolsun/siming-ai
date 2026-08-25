"""Canonicalize model-generated character role types.

Revision ID: 300a16_character_role_type_enum
Revises: 300a15_cataloging_review_warning
"""

from __future__ import annotations

import re

import sqlalchemy as sa

from alembic import op

revision = "300a16_character_role_type_enum"
down_revision = "300a15_cataloging_review_warning"
branch_labels = None
depends_on = None


def _canonical(value: object) -> str:
    text = str(value or "").strip().casefold()
    if text in {"protagonist", "supporting", "antagonist", "mentor", "other", "merged_alias"}:
        return text
    tokens = [item.strip() for item in re.split(r"[,，、/|;；\n]+", text)]
    if any(
        item in {"主角", "主人公", "男主", "女主", "lead", "protagonist"}
        or re.match(r"^(?:本书|故事)?(?:男|女)?主角(?:身份|定位)?(?:\s*[（(:：].*)?$", item)
        for item in tokens
    ):
        return "protagonist"
    if any(re.search(r"反派|敌对|宿敌|antagonist|villain", item) for item in tokens):
        return "antagonist"
    if any(re.search(r"导师|师父|师傅|引路人|mentor", item) for item in tokens):
        return "mentor"
    if any(re.search(r"配角|同伴|伙伴|家人|亲属|父亲|母亲|support", item) for item in tokens):
        return "supporting"
    return "other"


def _role_details(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.casefold() == "merged_alias":
        return ""
    canonical_tokens = {
        "protagonist", "supporting", "antagonist", "mentor", "other",
        "主角", "主人公", "男主", "女主", "配角", "反派", "导师",
    }
    details = []
    for raw in re.split(r"[,，、/|;；\n]+", text):
        token = raw.strip()
        if not token or token.casefold() in canonical_tokens:
            continue
        if token not in details:
            details.append(token)
    return "、".join(details)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "characters" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("characters")}
    if not {"id", "role_type"} <= columns:
        return
    characters = sa.table(
        "characters",
        sa.column("id", sa.String()),
        sa.column("role_type", sa.String()),
        sa.column("background", sa.Text()),
    )
    selected = [characters.c.id, characters.c.role_type]
    has_background = "background" in columns
    if has_background:
        selected.append(characters.c.background)
    for row in bind.execute(sa.select(*selected)).mappings():
        current = row["role_type"]
        canonical = _canonical(current)
        values: dict[str, object] = {"role_type": canonical}
        details = _role_details(current)
        if has_background and details:
            background = str(row.get("background") or "").strip()
            sentence = f"身份补充：{details}"
            if details not in background:
                values["background"] = f"{background}\n\n{sentence}".strip()[:8000]
        if current != canonical or len(values) > 1:
            bind.execute(
                characters.update().where(characters.c.id == row["id"]).values(**values)
            )


def downgrade() -> None:
    # Canonical values are valid in older releases; original free-form model
    # prose cannot be reconstructed safely.
    pass
