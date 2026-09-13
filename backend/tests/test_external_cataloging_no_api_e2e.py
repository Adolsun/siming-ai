"""External tools complete the same plan without invoking a Siming API model."""
import asyncio
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, Project, Chapter, Character, CatalogingJob, CatalogingCandidate, ChapterSummary
from app.services.cataloging.orchestrator import LLMGateway
from app.services.workspace.tools import external_cataloging as tools
from app.services.workspace.tools.cataloging import apply_pending_cataloging
from tests.test_cataloging_plan import plan_rows


def call(fn, db, args, project='p'):
    return asyncio.run(fn(db, project, args))


@pytest.fixture
def external_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'external.db').as_posix()}")
    Base.metadata.create_all(engine)
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected Siming model API call')
    monkeypatch.setattr(LLMGateway, 'stream_chat_completion_with_tools', forbidden)
    def mirror(db, project, chapter, **kwargs):
        path = tmp_path / f'{chapter.id}.txt'
        path.write_text(chapter.content, encoding='utf-8')
        return tmp_path, path
    monkeypatch.setattr(tools, 'ensure_chapter_mirror', mirror)
    with sessionmaker(bind=engine)() as db:
        db.add(Project(id='p', title='外部建档'))
        db.add_all([Chapter(id=f'c{i}', project_id='p', title=f'第{i}章', content='炉灵与少年交谈。', sort_order=i) for i in range(1,4)])
        db.add(Character(id='real-character', project_id='p', name='炉灵'))
        db.commit()
        yield db
    engine.dispose()


def start(db):
    receipt = call(tools.start_external_cataloging_job, db, {})
    assert receipt['status'] == 'ok', receipt
    return db.get(CatalogingJob, receipt['data']['job_id'])


def test_full_three_chapter_workflow_without_model_api(external_db):
    db = external_db
    job = start(db)
    for index in range(1,4):
        current = call(tools.get_next_external_cataloging_chapter, db, {'job_id':job.id})['data']
        assert current['chapter_id'] == f'c{index}'
        rows = plan_rows(db.get(Character,'real-character'))
        rows[1]['title'] = current['title']
        receipt = call(tools.save_external_cataloging_candidates,db,{'job_id':job.id,'chapter_id':current['chapter_id'],'candidates':rows,'finalize':True})
        assert receipt['data']['candidate_set_complete'], receipt
        assert db.query(ChapterSummary).count() == index-1
        receipt = call(apply_pending_cataloging,db,{'job_id':job.id})
        assert receipt['status'] == 'ok', receipt
        db.commit()
        assert call(tools.verify_external_cataloging_progress,db,{'job_id':job.id})['data']['chapters_processed'] == index
    assert job.status == 'completed'
    assert db.query(Character).count() == 1
    assert db.query(ChapterSummary).count() == 3
    assert call(tools.get_next_external_cataloging_chapter,db,{'job_id':job.id})['data']['all_done']


def test_file_reads_and_idempotent_start(external_db):
    db = external_db
    job = start(db)
    assert start(db).id == job.id
    data = call(tools.get_next_external_cataloging_chapter,db,{'job_id':job.id,'include_content':False,'include_prompt_pack':False})['data']
    assert data['content'] is None and data['prompt_pack'] is None
    assert Path(data['content_file_path']).read_text(encoding='utf-8') == db.get(Chapter,'c1').content
    assert data['chapter_version'] == db.get(Chapter,'c1').current_version


def test_partial_plan_cannot_advance_and_can_be_completed_incrementally(external_db):
    db = external_db
    job = start(db)
    rows = plan_rows()
    receipt = call(tools.save_external_cataloging_candidates,db,{'job_id':job.id,'chapter_id':'c1','candidates':[rows[0],{**rows[1],'character_ids':'[]'}],'finalize':True})
    assert not receipt['data']['candidate_set_complete'] and receipt['data']['candidate_errors']
    summary_id = db.query(CatalogingCandidate).one().id
    data = call(tools.verify_external_cataloging_progress,db,{'job_id':job.id})['data']
    assert data['next_tool'] == 'get_next_external_cataloging_chapter'
    assert 'phase' not in data['next_arguments']
    blocked = call(tools.save_external_cataloging_candidates,db,{'job_id':job.id,'chapter_id':'c2','candidates':rows,'finalize':True})
    assert blocked['status'] != 'ok'
    assert db.query(CatalogingCandidate).filter_by(chapter_id='c2').count() == 0
    assert call(apply_pending_cataloging,db,{'job_id':job.id})['status'] != 'ok'
    receipt = call(tools.save_external_cataloging_candidates,db,{'job_id':job.id,'chapter_id':'c1','candidates':[rows[1]],'finalize':True})
    assert receipt['data']['candidate_set_complete'], receipt
    assert db.query(CatalogingCandidate).filter_by(item_type='chapter_summary').one().id == summary_id


def test_managed_binding_rejects_another_project_or_chapter(external_db, monkeypatch):
    db = external_db
    job = start(db)
    for key,value in {'KIND':'cataloging','CATALOGING_PROJECT_ID':'p','CATALOGING_JOB_ID':job.id,'CATALOGING_CHAPTER_ID':'c1'}.items():
        monkeypatch.setenv('SIMING_MANAGED_AGENT_KIND' if key=='KIND' else 'SIMING_MANAGED_'+key,value)
    for project,chapter in (('foreign','c1'),('p','c2')):
        receipt = call(tools.save_external_cataloging_candidates,db,{'job_id':job.id,'chapter_id':chapter,'candidates':plan_rows(),'finalize':True},project)
        assert receipt['status'] != 'ok'
    assert db.query(CatalogingCandidate).count() == 0
