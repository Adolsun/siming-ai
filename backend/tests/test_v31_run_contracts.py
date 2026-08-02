"""Focused contracts for v3.1 durable creation and assistant runs."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    NovelCreationRunClaim,
    NovelCreationSession,
    NovelCreationStageRun,
    OperationRun,
)
from app.database.session import Base
from app.main import app
from app.modules.creation.infrastructure.session_store import SqlAlchemyNovelCreationSessionStore
from app.services.novel_creation_claims import (
    claim_or_replay_creation_run,
    creation_idempotency_key,
)
from app.services.novel_creation_runs import (
    create_run,
    complete_run,
    confirm_run,
    mark_interrupted_novel_creation_runs,
    serialize_run,
)
from app.services.novel_creation_stage_execution import _capture_model_diagnostic
from app.services.novel_creation_task_runtime import invoke_durable_creation_action
from app.services.novel_creation_workspace import serialize_session
from app.services.workspace.run_log import resolve_assistant_model
from app.routers.novel_creation import (
    CreationConversationCommandRequest,
    creation_conversation_command,
)


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


def test_creation_artifact_openapi_exposes_query_patch_lock_and_confirm_routes() -> None:
    paths = app.openapi()["paths"]
    artifact_path = "/api/v1/novel-creation/sessions/{session_id}/artifacts/{stage}"
    lock_path = artifact_path + "/locks"
    assert "get" in paths[artifact_path]
    assert "patch" in paths[artifact_path]
    assert "get" in paths[artifact_path + "/dependencies"]
    assert "post" in paths[lock_path]
    assert "delete" in paths[lock_path]
    assert "post" in paths[artifact_path + "/undo"]
    assert "post" in paths["/api/v1/novel-creation/sessions/{session_id}/stages/{stage}/confirm"]
    assert "post" in paths["/api/v1/novel-creation/sessions/{session_id}/stages/{stage}/confirm-and-generate-recommended"]

    patch_schema = paths[artifact_path]["patch"]["requestBody"]["content"]["application/json"]["schema"]
    assert "NovelCreationArtifactPatchRequest" in patch_schema["$ref"]


def test_creation_claim_replays_identical_stage_command() -> None:
    db = _db()
    session = NovelCreationSession(mode="internal_llm", status="drafting", draft_json={"stages": {}})
    db.add(session)
    db.flush()
    key = creation_idempotency_key(
        session_id=session.id,
        stage="characters",
        operation="generate",
        request={"instruction": None, "model": None},
        input_revision=0,
        input_snapshot_hash="snapshot",
    )

    claim, replayed = claim_or_replay_creation_run(
        db,
        session_id=session.id,
        artifact_key="characters",
        idempotency_key=key,
        input_revision=0,
        input_snapshot_hash="snapshot",
    )
    duplicate, duplicate_replayed = claim_or_replay_creation_run(
        db,
        session_id=session.id,
        artifact_key="characters",
        idempotency_key=key,
        input_revision=0,
        input_snapshot_hash="snapshot",
    )

    assert replayed is False
    assert duplicate_replayed is True
    assert duplicate.id == claim.id


def test_chat_command_starts_targeted_creation_run_without_navigation() -> None:
    db = _db()
    session = NovelCreationSession(
        mode="internal_llm",
        status="drafting",
        revision=4,
        draft_json={"stages": {}},
    )
    db.add(session)
    db.commit()

    def capture_task(coro):
        coro.close()
        return MagicMock()

    with patch("app.routers.novel_creation.asyncio.create_task", side_effect=capture_task):
        response = asyncio.run(creation_conversation_command(
            CreationConversationCommandRequest(
                session_id=session.id,
                stage="characters",
                instruction="主角不动，重做反派",
                action="refine_artifact",
            ),
            db,
        ))

    assert response.data["run"]["stage"] == "characters"
    assert response.data["run"]["operation"] == "refine"
    assert response.data["ui_directive"]["navigate"] is False
    assert db.query(NovelCreationRunClaim).filter_by(session_id=session.id).count() == 1


def test_creation_run_supports_durable_pause_and_checkpoint_resume() -> None:
    db = _db()
    Session = sessionmaker(bind=db.bind)
    session = NovelCreationSession(mode="internal_llm", status="drafting", draft_json={"stages": {}})
    db.add(session)
    db.flush()
    run = create_run(db, session, "characters", {"model": "openai:test"})
    db.commit()

    assert db.get(OperationRun, run.operation_id).can_pause is True
    with patch("app.services.novel_creation_task_runtime.SessionLocal", Session):
        assert asyncio.run(invoke_durable_creation_action(run.operation_id, "pause")) is True
    db.expire_all()
    assert db.get(NovelCreationStageRun, run.id).status == "paused"

    with (
        patch("app.services.novel_creation_task_runtime.SessionLocal", Session),
        patch("app.services.novel_creation_task_runtime.schedule_creation_stage") as schedule,
    ):
        assert asyncio.run(invoke_durable_creation_action(run.operation_id, "continue")) is True
    db.expire_all()
    resumed = db.get(NovelCreationStageRun, run.id)
    assert resumed.status == "running"
    assert resumed.events[-1].event_type == "continued"
    assert schedule.call_args.args[:2] == (run.id, session.id)
    assert schedule.call_args.args[2]["_resume"] is True


def test_repaired_model_reply_is_kept_in_full_diagnostics_only() -> None:
    run = SimpleNamespace(diagnostics_json=None)
    context = SimpleNamespace(run=run)
    raw = "x" * 20_000
    metadata = {
        "result_mode": "repaired",
        "repair_method": "model_json",
        "warning": "结构已修复",
        "original_response_excerpt": raw[:12_000],
        "_diagnostic_raw": raw,
    }

    _capture_model_diagnostic(context, "characters", metadata)

    assert "_diagnostic_raw" not in metadata
    assert len(metadata["original_response_excerpt"]) == 12_000
    assert run.diagnostics_json[0]["raw_response"] == raw


def test_completed_generation_waits_for_author_confirmation() -> None:
    db = _db()
    session = NovelCreationSession(mode="internal_llm", status="drafting")
    db.add(session)
    db.flush()
    operation = OperationRun(
        source_kind="novel_creation",
        source_id="generation-run",
        title="characters",
        status="running",
    )
    db.add(operation)
    db.flush()
    run = NovelCreationStageRun(
        session_id=session.id,
        stage="characters",
        operation="generate",
        status="running",
        storage_target="session_draft",
        operation_id=operation.id,
    )
    db.add(run)
    db.flush()

    complete_run(db, run, {"result_mode": "model"})
    db.flush()
    db.refresh(run)

    assert run.status == "waiting_user"
    assert run.events[-1].event_type == "waiting_user"
    operation = db.get(OperationRun, run.operation_id)
    assert operation is not None
    assert operation.status == "waiting_user"
    assert operation.result_json["summary"] == run.current_message

    assert confirm_run(db, run) is True
    db.flush()
    db.refresh(run)
    assert run.status == "completed"
    assert run.events[-1].event_type == "author_confirmed"


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
    claim = NovelCreationRunClaim(
        session_id=session.id,
        artifact_key="characters",
        idempotency_key="restart-claim",
        claim_token="claim-token",
        status="running",
        input_revision=0,
        input_snapshot_hash="snapshot",
    )
    db.add_all([run, claim])
    db.flush()
    run.claim_id = claim.id
    db.commit()

    assert mark_interrupted_novel_creation_runs(db) == 1
    db.commit()
    db.refresh(run)

    assert run.status == "interrupted"
    assert run.failure_class == "interrupted"
    assert run.events[-1].event_type == "interrupted"
    assert serialize_run(run)["run_id"] == run.id
    assert SqlAlchemyNovelCreationSessionStore(db).running_stage(session.id, "characters") is None
    assert db.get(NovelCreationRunClaim, claim.id).status == "interrupted"


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
