"""Bridge canonical scoped conversations to workspace execution threads.

Revision ID: 300a9_canonical_conversation_bridge
Revises: 300a8_unified_conversation_scope
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "300a9_canonical_conversation_bridge"
down_revision = "300a8_unified_conversation_scope"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "assistant_conversations" not in _tables():
        return
    if "canonical_conversation_id" not in _columns("assistant_conversations"):
        op.add_column(
            "assistant_conversations",
            sa.Column("canonical_conversation_id", sa.String(length=36), nullable=True),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("assistant_conversations")}
    if "ux_assistant_conversations_canonical" not in indexes:
        op.create_index(
            "ux_assistant_conversations_canonical",
            "assistant_conversations",
            ["canonical_conversation_id"],
            unique=True,
        )


def downgrade() -> None:
    if "assistant_conversations" not in _tables():
        return
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("assistant_conversations")}
    if "ux_assistant_conversations_canonical" in indexes:
        op.drop_index("ux_assistant_conversations_canonical", table_name="assistant_conversations")
    if "canonical_conversation_id" in _columns("assistant_conversations"):
        op.drop_column("assistant_conversations", "canonical_conversation_id")
