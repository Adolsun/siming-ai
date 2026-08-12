"""Separate cataloging review warnings from hard failures.

Revision ID: 300a15_cataloging_review_warning
Revises: 300a14_cataloging_outline_hierarchy
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "300a15_cataloging_review_warning"
down_revision = "300a14_cataloging_outline_hierarchy"
branch_labels = None
depends_on = None


_REVIEW_PREFIX = "候选已保留，需要核对模型抽取的原文线索："


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cataloging_chapter_runs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("cataloging_chapter_runs")}
    if "review_warning" not in columns:
        op.add_column("cataloging_chapter_runs", sa.Column("review_warning", sa.Text(), nullable=True))

    runs = sa.table(
        "cataloging_chapter_runs",
        sa.column("error", sa.Text()),
        sa.column("review_warning", sa.Text()),
    )
    bind.execute(
        runs.update()
        .where(runs.c.error.like(f"{_REVIEW_PREFIX}%"))
        .values(review_warning=runs.c.error, error=None)
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cataloging_chapter_runs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("cataloging_chapter_runs")}
    if "review_warning" in columns:
        op.drop_column("cataloging_chapter_runs", "review_warning")
