"""Persist complete model diagnostics for repaired creation runs.

Revision ID: 300a10_creation_run_diagnostics
Revises: 300a9_canonical_conversation_bridge
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "300a10_creation_run_diagnostics"
down_revision = "300a9_canonical_conversation_bridge"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "novel_creation_stage_runs" not in inspector.get_table_names():
        return set()
    return {item["name"] for item in inspector.get_columns("novel_creation_stage_runs")}


def upgrade() -> None:
    columns = _columns()
    if not columns:
        return
    if "diagnostics_json" not in columns:
        op.add_column("novel_creation_stage_runs", sa.Column("diagnostics_json", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE novel_creation_stage_runs SET status = 'waiting_user' WHERE status = 'waiting_author'"
    )


def downgrade() -> None:
    if not _columns():
        return
    op.execute(
        "UPDATE novel_creation_stage_runs SET status = 'waiting_author' WHERE status = 'waiting_user'"
    )
    if "diagnostics_json" in _columns():
        op.drop_column("novel_creation_stage_runs", "diagnostics_json")
