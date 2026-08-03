"""Add canonical scope fields to durable system conversations.

Revision ID: 300a8_unified_conversation_scope
Revises: 300a7_creation_entities_history
Create Date: 2026-08-02
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "300a8_unified_conversation_scope"
down_revision = "300a7_creation_entities_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "system_assistant_conversations" not in set(inspector.get_table_names()):
        # Sparse stamped alpha databases are completed by bootstrap create_all
        # after Alembic reaches head.
        return
    columns = {item["name"] for item in inspector.get_columns("system_assistant_conversations")}
    with op.batch_alter_table("system_assistant_conversations") as batch:
        if "scope_type" not in columns:
            batch.add_column(sa.Column("scope_type", sa.String(length=30), nullable=False, server_default="system"))
        if "scope_id" not in columns:
            batch.add_column(sa.Column("scope_id", sa.String(length=36), nullable=True))
        if "project_id" not in columns:
            batch.add_column(sa.Column("project_id", sa.String(length=36), nullable=True))
            batch.create_foreign_key(
                "fk_system_assistant_conversation_project",
                "projects",
                ["project_id"],
                ["id"],
                ondelete="SET NULL",
            )
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("system_assistant_conversations")}
    if "ix_system_assistant_conversation_scope" not in indexes:
        op.create_index(
            "ix_system_assistant_conversation_scope",
            "system_assistant_conversations",
            ["scope_type", "scope_id", "updated_at"],
        )
    op.execute(
        "UPDATE system_assistant_conversations "
        "SET scope_type = CASE WHEN creation_session_id IS NOT NULL THEN 'creation' ELSE 'system' END, "
        "scope_id = creation_session_id WHERE scope_id IS NULL"
    )


def downgrade() -> None:
    if "system_assistant_conversations" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.drop_index("ix_system_assistant_conversation_scope", table_name="system_assistant_conversations")
    with op.batch_alter_table("system_assistant_conversations") as batch:
        batch.drop_constraint("fk_system_assistant_conversation_project", type_="foreignkey")
        batch.drop_column("project_id")
        batch.drop_column("scope_id")
        batch.drop_column("scope_type")
