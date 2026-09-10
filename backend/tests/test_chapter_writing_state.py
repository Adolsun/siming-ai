"""Author actions outside chat must update the model's next-step state."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, CatalogingChapterRun, CatalogingJob, Chapter, ChapterDraft, Project
from app.services.workspace.chapter_writing_state import load_chapter_writing_state


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        session.add(Project(id="p1", title="Novel"))
        session.commit()
        yield session
    engine.dispose()


def test_author_save_cataloging_completion_and_later_edit_have_distinct_states(db):
    draft = ChapterDraft(id="d1", project_id="p1", title="Chapter", content="Draft", status="pending")
    db.add(draft)
    db.commit()
    state = load_chapter_writing_state(db, "p1")
    assert state["pending_draft"]["id"] == "d1"
    assert state["cataloging_required_chapter"] is None

    chapter = Chapter(id="c1", project_id="p1", title="Chapter", content="Saved", cataloging_required=True)
    db.add(chapter)
    draft.status, draft.saved_chapter_id = "saved", "c1"
    db.commit()
    state = load_chapter_writing_state(db, "p1")
    assert state["pending_draft"] is None
    assert state["cataloging_required_chapter"]["id"] == "c1"

    job = CatalogingJob(id="j1", project_id="p1", status="running", model_source="chapter_save:explicit")
    db.add(job)
    db.flush()
    run = CatalogingChapterRun(id="r1", job_id="j1", project_id="p1", chapter_id="c1", chapter_version=1, status="extracting")
    db.add(run)
    db.commit()
    assert load_chapter_writing_state(db, "p1")["blocking_cataloging_job"]["id"] == "j1"

    job.status, run.status, chapter.cataloging_required = "completed", "completed", False
    db.commit()
    assert load_chapter_writing_state(db, "p1") == {
        "pending_draft": None, "blocking_cataloging_job": None, "cataloging_required_chapter": None,
    }
    # Completing v1 must not release a later author-edited v2.
    chapter.current_version, chapter.cataloging_required = 2, True
    db.commit()
    state = load_chapter_writing_state(db, "p1")
    assert state["pending_draft"] is None
    assert state["cataloging_required_chapter"]["current_version"] == 2


@pytest.mark.parametrize("status", ["saved", "discarded", "superseded"])
def test_handled_drafts_and_other_projects_do_not_become_current_blockers(db, status):
    db.add(Project(id="p2", title="Other"))
    db.add_all([
        ChapterDraft(id="handled", project_id="p1", title="Handled", content="Draft", status=status),
        ChapterDraft(id="foreign", project_id="p2", title="Other", content="Draft", status="pending"),
        Chapter(id="foreign-chapter", project_id="p2", title="Other", content="Saved", cataloging_required=True),
    ])
    db.commit()
    assert all(value is None for value in load_chapter_writing_state(db, "p1").values())
