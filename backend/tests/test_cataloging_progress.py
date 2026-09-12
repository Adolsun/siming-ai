"""Real queued workers must be independent of HTTP progress subscribers."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    Base,
    CatalogingCandidate,
    CatalogingChapterRun,
    CatalogingFact,
    CatalogingJob,
    Chapter,
    Project,
)
from app.routers import cataloging as router
from app.services.cataloging import launcher, orchestrator, progress
from app.services.cataloging.fact_store import SOURCE_FACT_TYPES
from tests.test_cataloging_candidate_repair import summary_payload


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'catalog.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    for module in (router, launcher, orchestrator, progress):
        monkeypatch.setattr(module, "SessionLocal", sessions)
    monkeypatch.setattr(launcher, "_LAUNCH_TASKS", {})
    monkeypatch.setattr(progress, "POLL_SECONDS", 0.01)
    chapter_file = tmp_path / "chapter.txt"
    chapter_file.write_text("核验工作已经完成。", encoding="utf-8")
    monkeypatch.setattr(
        orchestrator, "ensure_chapter_mirror", lambda *a, **kw: (tmp_path, chapter_file)
    )
    # Operation heartbeats have their own global DB factory; keep that IO in
    # this database too. Worker, queue, extraction, apply, and HTTP are real.
    from app.modules.operations.infrastructure import runtime

    monkeypatch.setattr(runtime, "SessionLocal", sessions)
    with sessions() as db:
        db.add_all(
            [
                Project(id="p", title="建档并发回归"),
                Chapter(
                    id="c",
                    project_id="p",
                    title="核验",
                    content=chapter_file.read_text(encoding="utf-8"),
                ),
            ]
        )
        db.commit()
        job = orchestrator.create_cataloging_job(db, "p", "auto", "test:model", ["c"])
        job.status = "paused_on_failure"
        job.chapter_runs[0].status = "failed"
        job.chapter_runs[0].error = "此前失败"
        db.commit()
        job_id = job.id
    app = FastAPI()
    app.include_router(router.router)

    def request_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[router.get_db] = request_db
    yield app, sessions, job_id
    engine.dispose()


class Observer:
    """Exercise the actual ASGI streaming endpoint, including disconnects."""

    def __init__(self, app, job_id):
        self.ready = asyncio.Event()
        self.messages = []
        self.requests = asyncio.Queue()
        self.requests.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "root_path": "",
            "path": f"/projects/p/cataloging/{job_id}/stream",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
        }
        self.task = asyncio.create_task(app(scope, self.requests.get, self.send))

    async def send(self, message):
        self.messages.append(message)
        if message["type"] == "http.response.body":
            self.ready.set()

    async def disconnect(self):
        await self.requests.put({"type": "http.disconnect"})
        await asyncio.wait_for(self.task, 3)

    def events(self):
        body = b"".join(m.get("body", b"") for m in self.messages).decode()
        return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: {")]


def model_rows():
    summary = summary_payload()
    summary["summary_text"] = (
        "本章完成核验，所有材料已经逐项对照，记录了核验结论并保留原始凭证。" * 4
    )
    return [
        {"type": "chapter_summary", "payload": summary},
        {
            "character_ids": [],
            "type": "outline_create",
            "node_type": "chapter",
            "title": "核验",
            "summary": "核验工作完毕。",
        },
    ]


def test_retry_worker_runs_once_with_two_observers_and_disconnect_reconnect(catalog, monkeypatch):
    app, sessions, job_id = catalog

    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def model(messages, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                entered.set()
                await release.wait()
                rows = [{"fact_type": "chapter_overview", "payload": {"summary": "核验工作完毕。"}}]
            else:
                rows = model_rows()
            for row in rows:
                yield json.dumps(row, ensure_ascii=False) + "\n"
                await asyncio.sleep(0)

        monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion", model)
        observers = []
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(f"/projects/p/cataloging/{job_id}/retry-current")
                assert response.status_code == 200
                assert response.json()["data"]["worker_queued"] is True
            await asyncio.wait_for(entered.wait(), 3)
            worker = launcher._LAUNCH_TASKS[job_id]
            gui, phone = Observer(app, job_id), Observer(app, job_id)
            observers.extend([gui, phone])
            await asyncio.wait_for(asyncio.gather(gui.ready.wait(), phone.ready.wait()), 3)
            await gui.disconnect()
            assert not worker.done()
            reconnected = Observer(app, job_id)
            observers.append(reconnected)
            await asyncio.wait_for(reconnected.ready.wait(), 3)
            assert len(calls) == 1, "A progress connection started another extraction"
            assert launcher.queue_cataloging_job(job_id) is worker
            release.set()
            await asyncio.wait_for(asyncio.gather(worker, phone.task, reconnected.task), 10)
            with sessions() as db:
                job = db.get(CatalogingJob, job_id)
                assert job.status == "completed", job.error
                assert (
                    db.query(CatalogingFact)
                    .filter(CatalogingFact.fact_type.in_(SOURCE_FACT_TYPES))
                    .count()
                    == 1
                )
                assert db.query(CatalogingCandidate).count() == 2
                assert all(row.status == "applied" for row in db.query(CatalogingCandidate))
            assert len(calls) == 2  # One fact request, one candidate request.
            for observer in (phone, reconnected):
                events = observer.events()
                assert events[-1]["type"] == "completed"
                assert any(e.get("fact", {}).get("id") for e in events)
                assert any(
                    e["type"] == "cataloging_stage" and "第二阶段" in e.get("message", "")
                    for e in events
                )
            finished = Observer(app, job_id)
            observers.append(finished)
            await asyncio.wait_for(finished.task, 3)
            assert finished.events()[-1]["type"] == "completed"
            assert len(calls) == 2
        finally:
            release.set()
            for observer in observers:
                if not observer.task.done():
                    await observer.disconnect()
            tasks = list(launcher._LAUNCH_TASKS.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize("backend", ["internal_llm", "local_cli_agent", "external_agent"])
@pytest.mark.parametrize(
    "status", ["paused", "paused_on_failure", "waiting_confirmation", "cancelled", "completed"]
)
def test_observing_inactive_jobs_is_read_only(catalog, monkeypatch, backend, status):
    app, sessions, job_id = catalog
    with sessions() as db:
        job = db.get(CatalogingJob, job_id)
        job.execution_backend = backend
        job.execution_mode = "manual"
        job.status = status
        db.commit()

    def forbidden(*args, **kwargs):
        pytest.fail("Observing must not launch or execute a worker")

    monkeypatch.setattr(launcher, "queue_cataloging_job", forbidden)
    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion", forbidden)

    async def check():
        observer = Observer(app, job_id)
        await asyncio.wait_for(observer.task, 3)
        assert observer.events()[-1]["job"]["status"] == status

    asyncio.run(check())
    with sessions() as db:
        assert db.get(CatalogingJob, job_id).status == status
        assert db.query(CatalogingFact).count() == 0
        assert db.query(CatalogingCandidate).count() == 0


@pytest.mark.parametrize("command", ["http_mode", "workspace_mode", "apply_pending"])
def test_manual_confirmation_continues_without_opening_a_progress_stream(
    catalog, monkeypatch, command
):
    app, sessions, job_id = catalog
    with sessions() as db:
        db.get(CatalogingJob, job_id).execution_mode = "manual"
        db.commit()
    calls = []

    async def model(messages, **kwargs):
        calls.append(messages)
        rows = (
            [{"fact_type": "chapter_overview", "payload": {"summary": "核验工作完毕。"}}]
            if len(calls) == 1
            else model_rows()
        )
        for row in rows:
            yield json.dumps(row, ensure_ascii=False) + "\n"

    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion", model)

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(f"/projects/p/cataloging/{job_id}/retry-current")
            assert response.status_code == 200
            worker = launcher._LAUNCH_TASKS.get(job_id)
            if worker:
                await asyncio.wait_for(worker, 10)
            with sessions() as db:
                job = db.get(CatalogingJob, job_id)
                assert job.status == "waiting_confirmation", job.error
                assert all(c.status == "pending" for c in db.query(CatalogingCandidate))
            if command == "http_mode":
                response = await client.patch(
                    f"/projects/p/cataloging/{job_id}/mode", json={"execution_mode": "auto"}
                )
                assert response.status_code == 200
                assert response.json()["data"]["should_resume"] is True
            elif command == "workspace_mode":
                from app.services.workspace.tools.cataloging import set_cataloging_mode

                with sessions() as db:
                    result = await set_cataloging_mode(
                        db, "p", {"job_id": job_id, "execution_mode": "auto"}
                    )
                    db.commit()
                    assert result["status"] == "ok"
            else:
                response = await client.post(f"/projects/p/cataloging/{job_id}/apply-pending")
                assert response.status_code == 200
            worker = launcher._LAUNCH_TASKS.get(job_id)
            if worker:
                await asyncio.wait_for(worker, 10)
        with sessions() as db:
            job = db.get(CatalogingJob, job_id)
            assert job.status == "completed", job.error
            assert all(c.status == "applied" for c in db.query(CatalogingCandidate))
        assert len(calls) == 2

    asyncio.run(check())


def test_explicit_skip_queues_the_next_chapter_without_a_stream(catalog, monkeypatch):
    app, sessions, job_id = catalog
    with sessions() as db:
        db.add(Chapter(id="next", project_id="p", title="后续核验", content="继续核验。"))
        db.add(
            CatalogingChapterRun(
                job_id=job_id,
                project_id="p",
                chapter_id="next",
                chapter_order=1,
                chapter_version=1,
                status="pending",
            )
        )
        db.get(CatalogingJob, job_id).total_chapters = 2
        db.commit()
    calls = []

    async def model(messages, **kwargs):
        calls.append(messages)
        rows = (
            [{"fact_type": "chapter_overview", "payload": {"summary": "后续核验完毕。"}}]
            if len(calls) == 1
            else model_rows()
        )
        for row in rows:
            yield json.dumps(row, ensure_ascii=False) + "\n"

    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion", model)

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(f"/projects/p/cataloging/{job_id}/skip-current")
            assert response.status_code == 200
            worker = launcher._LAUNCH_TASKS.get(job_id)
            if worker:
                await asyncio.wait_for(worker, 10)
        with sessions() as db:
            job = db.get(CatalogingJob, job_id)
            assert job.status == "completed", job.error
            assert [r.status for r in sorted(job.chapter_runs, key=lambda r: r.chapter_order)] == [
                "skipped_by_user",
                "completed",
            ]
            assert db.query(CatalogingFact).filter_by(chapter_id="c").count() == 0
        assert len(calls) == 2

    asyncio.run(check())
