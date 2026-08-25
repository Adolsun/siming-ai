"""Close narrative governance lifecycle and coverage gaps.

Revision ID: 300a12_narrative_governance_loop
Revises: 300a11_operation_attention_read
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "300a12_narrative_governance_loop"
down_revision = "300a11_operation_attention_read"
branch_labels = None
depends_on = None


LIFECYCLE_COLUMNS = (
    sa.Column("source_chapter_version", sa.Integer(), nullable=True),
    sa.Column("resolved_chapter_version", sa.Integer(), nullable=True),
    sa.Column("resolution_note", sa.Text(), nullable=True),
    sa.Column("resolution_evidence", sa.Text(), nullable=True),
    sa.Column("verification_note", sa.Text(), nullable=True),
    sa.Column("verified_at", sa.DateTime(), nullable=True),
    sa.Column("last_checked_at", sa.DateTime(), nullable=True),
    sa.Column("stale_reason", sa.Text(), nullable=True),
    sa.Column("closed_by", sa.String(length=50), nullable=True),
)

QUALITY_COLUMNS = (
    sa.Column("total_score", sa.Float(), nullable=True),
    sa.Column("max_score", sa.Float(), nullable=True),
    sa.Column("dimension_scores", sa.JSON(), nullable=True),
    sa.Column("overall_assessment", sa.Text(), nullable=True),
    sa.Column("model", sa.String(length=300), nullable=True),
    sa.Column("chapter_version", sa.Integer(), nullable=True),
)


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    if table_name not in _table_names():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}


def _add_missing_columns(table_name: str, definitions: tuple[sa.Column, ...]) -> None:
    if table_name not in _table_names():
        return
    existing = _columns(table_name)
    for definition in definitions:
        if definition.name not in existing:
            op.add_column(
                table_name,
                sa.Column(
                    definition.name,
                    definition.type,
                    nullable=definition.nullable,
                ),
            )


def upgrade() -> None:
    for table_name in ("foreshadowings", "causal_edges", "narrative_debts"):
        _add_missing_columns(table_name, LIFECYCLE_COLUMNS)
    _add_missing_columns("chapter_quality_metrics", QUALITY_COLUMNS)

    tables = _table_names()
    if "chapter_governance_reviews" not in tables:
        op.create_table(
            "chapter_governance_reviews",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("chapter_id", sa.String(length=36), nullable=False),
            sa.Column("chapter_version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("source", sa.String(length=50), nullable=False),
            sa.Column("findings_count", sa.Integer(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("evidence", sa.Text(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_id",
                "chapter_id",
                "chapter_version",
                name="uq_chapter_governance_review_version",
            ),
        )
        op.create_index(
            "ix_chapter_governance_review_status",
            "chapter_governance_reviews",
            ["project_id", "status", "chapter_id"],
        )

    if "narrative_governance_events" not in tables:
        op.create_table(
            "narrative_governance_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("item_type", sa.String(length=40), nullable=False),
            sa.Column("item_id", sa.String(length=36), nullable=False),
            sa.Column("from_status", sa.String(length=30), nullable=True),
            sa.Column("to_status", sa.String(length=30), nullable=False),
            sa.Column("chapter_id", sa.String(length=36), nullable=True),
            sa.Column("chapter_version", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("actor", sa.String(length=50), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_narrative_governance_event_item",
            "narrative_governance_events",
            ["project_id", "item_type", "item_id", "created_at"],
        )


def downgrade() -> None:
    tables = _table_names()
    if "narrative_governance_events" in tables:
        op.drop_table("narrative_governance_events")
    if "chapter_governance_reviews" in tables:
        op.drop_table("chapter_governance_reviews")
    for table_name, definitions in (
        ("chapter_quality_metrics", QUALITY_COLUMNS),
        ("narrative_debts", LIFECYCLE_COLUMNS),
        ("causal_edges", LIFECYCLE_COLUMNS),
        ("foreshadowings", LIFECYCLE_COLUMNS),
    ):
        existing = _columns(table_name)
        for definition in reversed(definitions):
            if definition.name in existing:
                op.drop_column(table_name, definition.name)
