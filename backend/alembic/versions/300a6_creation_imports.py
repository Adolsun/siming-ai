"""Add durable novel-creation material imports.

Revision ID: 300a6_creation_imports
Revises: 300a5_creation_claims
Create Date: 2026-08-02
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "300a6_creation_imports"
down_revision = "300a5_creation_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "novel_creation_material_imports" not in tables:
        op.create_table(
            "novel_creation_material_imports",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("operation_id", sa.String(length=36), nullable=True),
            sa.Column("source_message_id", sa.String(length=36), nullable=True),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("stored_path", sa.Text(), nullable=False),
            sa.Column("media_type", sa.String(length=100), nullable=True),
            sa.Column("file_sha256", sa.String(length=64), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("input_revision", sa.Integer(), nullable=False),
            sa.Column("text_length", sa.Integer(), nullable=False),
            sa.Column("chunk_count", sa.Integer(), nullable=False),
            sa.Column("processed_chunks", sa.Integer(), nullable=False),
            sa.Column("checkpoint_json", sa.JSON(), nullable=True),
            sa.Column("preview_json", sa.JSON(), nullable=True),
            sa.Column("selection_json", sa.JSON(), nullable=True),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["session_id"], ["novel_creation_sessions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["operation_id"], ["operation_runs.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("session_id", "file_sha256", name="uq_novel_creation_import_file"),
        )
        op.create_index("ix_novel_creation_import_session", "novel_creation_material_imports", ["session_id", "created_at"])
        op.create_index("ix_novel_creation_import_status", "novel_creation_material_imports", ["status", "updated_at"])
    if "novel_creation_import_chunks" not in tables:
        op.create_table(
            "novel_creation_import_chunks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("import_run_id", sa.String(length=36), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("char_start", sa.Integer(), nullable=False),
            sa.Column("char_end", sa.Integer(), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("extraction_json", sa.JSON(), nullable=True),
            sa.Column("confidence", sa.Integer(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["import_run_id"], ["novel_creation_material_imports.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("import_run_id", "chunk_index", name="uq_novel_creation_import_chunk_index"),
        )
        op.create_index("ix_novel_creation_import_chunk_status", "novel_creation_import_chunks", ["import_run_id", "status"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "novel_creation_import_chunks" in tables:
        op.drop_table("novel_creation_import_chunks")
    if "novel_creation_material_imports" in tables:
        op.drop_table("novel_creation_material_imports")
