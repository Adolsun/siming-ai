"""Upgrade pauses incompatible checkpoints while preserving their audit data."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.database.models import CatalogingCandidate, CatalogingFact
from tests.test_cataloging_plan import archive  # noqa: F401


def test_upgrade_preserves_history_and_requires_a_current_plan(archive):
    db, job, run = archive
    run.status = "facts_saved"
    raw = '{"summary_text":"旧检查点"}'
    candidate = CatalogingCandidate(job_id=job.id, chapter_run_id=run.id, project_id=job.project_id,
        chapter_id=run.chapter_id, item_type="chapter_summary", raw_payload=raw)
    fact = CatalogingFact(job_id=job.id, chapter_run_id=run.id, project_id=job.project_id,
        chapter_id=run.chapter_id, fact_type="character_fact", raw_payload='{"name":"旧称呼"}')
    db.add_all([candidate, fact]); db.commit()
    ids = candidate.id, fact.id
    path = Path(__file__).resolve().parents[1] / "alembic/versions/300a37_cataloging_plan.py"
    spec = importlib.util.spec_from_file_location("cataloging_plan_upgrade", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(db.connection())):
        module.upgrade()
    db.commit(); db.expire_all()
    assert run.status == "failed" and job.status == "paused_on_failure"
    assert job.blocked_chapter_id == run.chapter_id
    assert db.get(CatalogingCandidate, ids[0]).raw_payload == raw
    assert db.get(CatalogingFact, ids[1]).raw_payload == '{"name":"旧称呼"}'
    assert "统一计划" in run.error
