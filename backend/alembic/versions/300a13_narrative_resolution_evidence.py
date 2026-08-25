"""Repair lifecycle evidence columns missing from an already-stamped schema.

Revision ID: 300a13_narrative_resolution_evidence
Revises: 300a12_narrative_governance_loop
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "300a13_narrative_resolution_evidence"
down_revision = "300a12_narrative_governance_loop"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    if table_name not in _table_names():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    # 300a12 was briefly shipped before this field was added to its source
    # file.  Databases already stamped at that revision never re-run a changed
    # migration, so the ORM could request a column that did not exist.  A new
    # immutable revision is the only safe repair.
    for table_name in ("foreshadowings", "causal_edges", "narrative_debts"):
        if table_name in _table_names() and "resolution_evidence" not in _columns(table_name):
            op.add_column(table_name, sa.Column("resolution_evidence", sa.Text(), nullable=True))


def downgrade() -> None:
    for table_name in ("narrative_debts", "causal_edges", "foreshadowings"):
        if "resolution_evidence" in _columns(table_name):
            op.drop_column(table_name, "resolution_evidence")
