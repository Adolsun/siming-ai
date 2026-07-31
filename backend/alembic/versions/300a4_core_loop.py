"""Add durable chapter-write reservations for Siming 3.1.

Revision ID: 300a4_core_loop
Revises: 300a3_gateway_sync
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "300a4_core_loop"
down_revision = "300a3_gateway_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chapter_write_claims" in inspector.get_table_names():
        return
    op.create_table(
        "chapter_write_claims",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("target_key", sa.String(length=300), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("claim_token", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("operation_id", sa.String(length=36), nullable=True),
        sa.Column("chapter_id", sa.String(length=36), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["assistant_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["operation_id"], ["operation_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "idempotency_key", name="uq_chapter_write_claim_identity"
        ),
    )
    op.create_index(
        "ix_chapter_write_claim_status",
        "chapter_write_claims",
        ["status", "updated_at"],
    )
    op.create_index("ix_chapter_write_claim_run", "chapter_write_claims", ["run_id"])
    op.create_index(
        "uq_chapter_write_claim_active_target",
        "chapter_write_claims",
        ["project_id", "target_key"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    if "chapter_write_claims" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("chapter_write_claims")
