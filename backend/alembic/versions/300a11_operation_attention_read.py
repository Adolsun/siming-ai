"""Persist operation-center attention read state.

Revision ID: 300a11_operation_attention_read
Revises: 300a10_creation_run_diagnostics
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "300a11_operation_attention_read"
down_revision = "300a10_creation_run_diagnostics"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "operation_runs" not in inspector.get_table_names():
        return set()
    return {item["name"] for item in inspector.get_columns("operation_runs")}


def upgrade() -> None:
    columns = _columns()
    if columns and "attention_read_at" not in columns:
        op.add_column("operation_runs", sa.Column("attention_read_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    if "attention_read_at" in _columns():
        op.drop_column("operation_runs", "attention_read_at")
