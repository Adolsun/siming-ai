"""Focused contracts for v3.1 durable creation and assistant runs."""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import NovelCreationSession, NovelCreationStageRun, OperationRun
from app.database.session import Base
from app.main import app
from app.modules.creation.infrastructure.session_store import SqlAlchemyNovelCreationSessionStore
from app.services.novel_creation_runs import (
    mark_interrupted_novel_creation_runs,
    serialize_run,
)
from app.services.novel_creation_workspace import serialize_session
from app.services.workspace.run_log import resolve_assistant_model


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_creation_run_openapi_exposes_durable_result_contract() -> None:
    schema = app.openapi()
    start_response = schema["paths"]["/api/v1/novel-creation/sessions/{session_id}/runs"]["post"]["responses"]["200"]
    query_response = schema["paths"]["/api/v1/novel-creation/runs/{run_id}"]["get"]["responses"]["200"]

    assert "NovelCreationStageRunStartData" in start_response["content"]["application/json"]["schema"]["$ref"]
    assert "NovelCreationStageRunResponse" in query_response["content"]["application/json"]["schema"]["$ref"]
    properties = schema["components"]["schemas"]["NovelCreationStageRunResponse"]["properties"]
    assert {
        "run_id",
        "operation_id",
        "status",
        "attempt",
        "result_mode",
        "warning",
    }.issubset(properties)


def test_restart_releases_interrupted_creation_run_for_retry() -> None:
    db = _db()
    session = NovelCreationSession(mode="internal_llm", status="drafting")
    operation = OperationRun(
        source_kind="novel_creation",
        source_id="stage-1",
        title="stage",
        status="interrupted",
    )
    db.add_all([session, operation])
    db.flush()
    run = NovelCreationStageRun(
        id="stage-1",
        session_id=session.id,
        stage="characters",
        operation="generate",
        status="running",
        storage_target="session_draft",
        operation_id=operation.id,
    )
    db.add(run)
    db.commit()

    assert mark_interrupted_novel_creation_runs(db) == 1
    db.commit()
    db.refresh(run)

    assert run.status == "interrupted"
    assert run.failure_class == "interrupted"
    assert run.events[-1].event_type == "interrupted"
    assert serialize_run(run)["run_id"] == run.id
    assert SqlAlchemyNovelCreationSessionStore(db).running_stage(session.id, "characters") is None


def test_assistant_model_is_resolved_to_actual_provider_identity() -> None:
    with patch(
        "app.services.workspace.run_log.LLMGateway.model_identity",
        return_value=("openai", "gpt-actual"),
    ):
        assert resolve_assistant_model(None) == "openai:gpt-actual"


def test_v2_session_is_read_as_v3_exploration_without_mutating_stored_draft() -> None:
    session = NovelCreationSession(
        id="legacy-session",
        mode="internal_llm",
        status="drafting",
        schema_version=2,
        draft_json={
            "schema_version": 2,
            "form": {"brief": "legacy author idea"},
            "concepts": [{"id": "legacy-concept", "title": "kept"}],
            "stages": {},
        },
    )

    payload = serialize_session(session, include_runs=False)

    assert payload["schema_version"] == 3
    assert payload["draft"]["schema_version"] == 3
    assert payload["draft"]["creation_mode"] == "explore"
    assert payload["draft"]["concepts"][0]["title"] == "kept"
    assert session.schema_version == 2
    assert "creation_mode" not in session.draft_json
