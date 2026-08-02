"""Add creation entities and immutable artifact history.

Revision ID: 300a7_creation_entities_history
Revises: 300a6_creation_imports
Create Date: 2026-08-02
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "300a7_creation_entities_history"
down_revision = "300a6_creation_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "novel_creation_artifact_versions" not in tables:
        op.create_table(
            "novel_creation_artifact_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("artifact_key", sa.String(length=100), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("source", sa.String(length=100), nullable=False),
            sa.Column("change_type", sa.String(length=40), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("change_summary_json", sa.JSON(), nullable=True),
            sa.Column("run_id", sa.String(length=36), nullable=True),
            sa.Column("operation_id", sa.String(length=36), nullable=True),
            sa.Column("parent_version_id", sa.String(length=36), nullable=True),
            sa.Column("restored_from_version_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["novel_creation_sessions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["run_id"], ["novel_creation_stage_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["operation_id"], ["operation_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["parent_version_id"], ["novel_creation_artifact_versions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["restored_from_version_id"], ["novel_creation_artifact_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "session_id", "artifact_key", "revision",
                name="uq_creation_artifact_version_revision",
            ),
        )
        op.create_index(
            "ix_creation_artifact_version_history",
            "novel_creation_artifact_versions",
            ["session_id", "artifact_key", "created_at"],
        )
    if "novel_creation_entities" not in tables:
        op.create_table(
            "novel_creation_entities",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("artifact_key", sa.String(length=100), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("entity_key", sa.String(length=180), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=100), nullable=False),
            sa.Column("data_json", sa.JSON(), nullable=False),
            sa.Column("provenance_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["session_id"], ["novel_creation_sessions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "session_id", "artifact_key", "entity_type", "entity_key",
                name="uq_creation_entity_identity",
            ),
        )
        op.create_index(
            "ix_creation_entity_list",
            "novel_creation_entities",
            ["session_id", "artifact_key", "entity_type", "status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "novel_creation_entities" in tables:
        op.drop_table("novel_creation_entities")
    if "novel_creation_artifact_versions" in tables:
        op.drop_table("novel_creation_artifact_versions")
