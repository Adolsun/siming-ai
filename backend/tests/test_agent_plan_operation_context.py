"""Plan HTTP recovery endpoints retain their assistant operation owner."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import ValidationError
from app.database.models import AssistantRun, Base, OperationRun, Project
from app.modules.operations.application.context import current_operation_id
from app.routers.agent import CreatePlanRequest, create_plan, execute_plan_stream, retry_step
from app.services.agent.orchestrator import PlanOrchestrator
from app.services.agent.plan_graph import PlanGraph, StepDef


@pytest.fixture()
def plan_context():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    project = Project(title="计划恢复上下文测试")
    operation = OperationRun(source_kind="assistant", source_id="context-test", title="context")
    session.add_all([project, operation])
    session.flush()
    run = AssistantRun(project_id=project.id, operation_id=operation.id)
    session.add(run)
    session.flush()
    plan = PlanOrchestrator(session, project.id).create_plan(
        PlanGraph(name="context", steps={"probe": StepDef(tool="probe", depends_on=[])}),
        assistant_run_id=run.id,
    )
    yield session, project, operation, plan
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_execute_stream_activates_original_operation(plan_context):
    session, project, operation, plan = plan_context

    async def probe(_db, _project_id, action):
        assert current_operation_id() == operation.id
        return {"tool": action["tool"], "status": "ok", "detail": "owner preserved", "data": {}}

    async def exercise():
        with (
            patch("app.services.agent.orchestrator.execute_workspace_action", side_effect=probe),
            patch(
                "app.services.workspace.assistant_stream_runtime.SessionLocal",
                return_value=session,
            ),
        ):
            response = await execute_plan_stream(project.id, plan.id, session)
            return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(exercise())

    assert any("owner preserved" in str(chunk) for chunk in chunks)


def test_retry_activates_original_operation(plan_context):
    session, project, operation, plan = plan_context
    step = plan.steps[0]
    step.status = "error"
    session.commit()

    async def probe(_db, _project_id, action):
        assert current_operation_id() == operation.id
        return {"tool": action["tool"], "status": "ok", "detail": "retried", "data": {}}

    async def exercise():
        with patch("app.services.agent.orchestrator.execute_workspace_action", side_effect=probe):
            return await retry_step(project.id, plan.id, step.step_key, session)

    response = asyncio.run(exercise())

    assert response.data["status"] == "ok"


def test_create_plan_rejects_cross_project_assistant_run(plan_context):
    session, project, _operation, _plan = plan_context
    foreign_project = Project(title="其他作品")
    session.add(foreign_project)
    session.flush()
    foreign_run = AssistantRun(project_id=foreign_project.id)
    session.add(foreign_run)
    session.commit()

    with pytest.raises(ValidationError, match="不属于当前作品"):
        asyncio.run(create_plan(
            project.id,
            CreatePlanRequest(
                mode="fast",
                outline_node_id="outline",
                assistant_run_id=foreign_run.id,
            ),
            session,
        ))
