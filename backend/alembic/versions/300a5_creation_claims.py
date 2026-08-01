"""Add durable novel-creation command claims.

Revision ID: 300a5_creation_claims
Revises: 300a4_core_loop
Create Date: 2026-08-01
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "300a5_creation_claims"
down_revision = "300a4_core_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "novel_creation_run_claims" not in tables:
        op.create_table(
            "novel_creation_run_claims",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("artifact_key", sa.String(length=100), nullable=False),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("claim_token", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("input_revision", sa.Integer(), nullable=False),
            sa.Column("input_snapshot_hash", sa.String(length=64), nullable=False),
            sa.Column("run_id", sa.String(length=36), nullable=True),
            sa.Column("operation_id", sa.String(length=36), nullable=True),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["session_id"], ["novel_creation_sessions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["run_id"], ["novel_creation_stage_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["operation_id"], ["operation_runs.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("session_id", "idempotency_key", name="uq_novel_creation_claim_identity"),
        )
        op.create_index("ix_novel_creation_claim_status", "novel_creation_run_claims", ["status", "updated_at"])
        op.create_index(
            "uq_novel_creation_claim_active_target",
            "novel_creation_run_claims",
            ["session_id", "artifact_key"],
            unique=True,
            sqlite_where=sa.text("status = 'running'"),
            postgresql_where=sa.text("status = 'running'"),
        )

    if "novel_creation_stage_runs" in tables:
        columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("novel_creation_stage_runs")
        }
        with op.batch_alter_table("novel_creation_stage_runs") as batch:
            if "idempotency_key" not in columns:
                batch.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
            if "claim_id" not in columns:
                batch.add_column(sa.Column("claim_id", sa.String(length=36), nullable=True))
            if "retry_of_run_id" not in columns:
                batch.add_column(sa.Column("retry_of_run_id", sa.String(length=36), nullable=True))

    inspector = sa.inspect(bind)
    if "system_assistant_messages" in inspector.get_table_names():
        message_columns = {
            column["name"] for column in inspector.get_columns("system_assistant_messages")
        }
        with op.batch_alter_table("system_assistant_messages") as batch:
            if "run_id" not in message_columns:
                batch.add_column(sa.Column("run_id", sa.String(length=36), nullable=True))
            if "operation_id" not in message_columns:
                batch.add_column(sa.Column("operation_id", sa.String(length=36), nullable=True))
            if "message_type" not in message_columns:
                batch.add_column(
                    sa.Column(
                        "message_type",
                        sa.String(length=30),
                        nullable=False,
                        server_default="text",
                    )
                )


def downgrade() -> None:
    bind = op.get_bind()
    if "system_assistant_messages" in sa.inspect(bind).get_table_names():
        message_columns = {
            column["name"] for column in sa.inspect(bind).get_columns("system_assistant_messages")
        }
        with op.batch_alter_table("system_assistant_messages") as batch:
            for column_name in ("message_type", "operation_id", "run_id"):
                if column_name in message_columns:
                    batch.drop_column(column_name)
    if "novel_creation_stage_runs" in sa.inspect(bind).get_table_names():
        with op.batch_alter_table("novel_creation_stage_runs") as batch:
            batch.drop_column("retry_of_run_id")
            batch.drop_column("claim_id")
            batch.drop_column("idempotency_key")
    if "novel_creation_run_claims" in sa.inspect(bind).get_table_names():
        op.drop_table("novel_creation_run_claims")
