"""Retire incomplete two-phase runs without guessing their entity bindings."""
from alembic import op
import sqlalchemy as sa

revision = "300a37_cataloging_plan"
down_revision = "300a36_outline_projection_identity"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if "cataloging_chapter_runs" not in sa.inspect(connection).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(connection).get_columns("cataloging_chapter_runs")}
    if not {"status", "error", "job_id", "chapter_id", "chapter_order"} <= columns:
        # Very old partially initialized databases are repaired by bootstrap.
        # They have no usable checkpoint state to convert in this data migration.
        return
    # Historical facts/candidates/apply logs stay available for inspection.
    # They cannot be silently upgraded into a model-selected identity plan.
    connection.execute(sa.text("""
        UPDATE cataloging_chapter_runs SET status='failed',
            error='建档契约已升级为统一计划；历史候选已保留，请修正计划后继续'
        WHERE status IN ('facts_saved','extracting','in_progress','awaiting_confirmation','applying')
    """))
    tables = sa.inspect(connection).get_table_names()
    if "cataloging_jobs" not in tables:
        return
    columns = {column["name"] for column in sa.inspect(connection).get_columns("cataloging_jobs")}
    if not {"id", "status", "error", "blocked_chapter_id"} <= columns:
        return
    connection.execute(sa.text("""
        UPDATE cataloging_jobs SET status='paused_on_failure',
            error='建档契约已升级；请保留候选并修正当前章节计划',
            blocked_chapter_id=(SELECT chapter_id FROM cataloging_chapter_runs
                WHERE job_id=cataloging_jobs.id AND status='failed' ORDER BY chapter_order LIMIT 1)
        WHERE status NOT IN ('completed','cancelled') AND EXISTS (
            SELECT 1 FROM cataloging_chapter_runs WHERE job_id=cataloging_jobs.id AND status='failed')
    """))


def downgrade():
    # A semantic decision cannot be synthesized by reversing a schema migration.
    pass
