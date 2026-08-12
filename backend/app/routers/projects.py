"""Project HTTP interface."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..architecture.uow import commit_session
from ..core.response import ApiResponse
from ..database.session import get_db
from ..modules.story.application.commands import StoryCommandContext
from ..modules.story.application.projects import ProjectWorkspace
from ..modules.story.interfaces.dependencies import get_story_command
from ..modules.story.interfaces.project_dependencies import get_project_workspace
from ..schemas.project import (
    ProjectCreate,
    ProjectListData,
    ProjectResponse,
    ProjectUpdate,
)

router = APIRouter(tags=["projects"])


class ProjectStorageRepairRequest(BaseModel):
    action: Literal["import_orphans", "refresh_mirror"] = Field(...)


class ProjectCreationBriefPatchRequest(BaseModel):
    """Author-controlled updates to a formal project's creation brief."""

    expected_revision: int | None = Field(None, ge=0)
    constraints: dict[str, Any] | None = None
    creative_direction: dict[str, Any] | None = None
    world_style: dict[str, Any] | None = None


@router.get("/projects", response_model=ApiResponse[ProjectListData])
def list_projects(
    workspace: Annotated[ProjectWorkspace, Depends(get_project_workspace)],
    q: str | None = Query(None, description="Search keyword for title or description"),
):
    return ApiResponse.success(data=workspace.list(q))


@router.post("/projects", response_model=ApiResponse[ProjectResponse])
def create_project(
    payload: ProjectCreate,
    workspace: Annotated[ProjectWorkspace, Depends(get_project_workspace)],
    command: Annotated[StoryCommandContext, Depends(get_story_command)],
):
    result = workspace.create(payload.model_dump())
    command.queue_all(result.sync_intents)
    command.finish()
    return ApiResponse.success(data=result.data, message="作品创建成功")


@router.get("/projects/{project_id}", response_model=ApiResponse[ProjectResponse])
def get_project(
    project_id: str,
    workspace: Annotated[ProjectWorkspace, Depends(get_project_workspace)],
):
    return ApiResponse.success(data=workspace.get(project_id))


@router.get("/projects/{project_id}/creation-brief")
def get_project_creation_brief(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Read the authoritative, editable brief linked to a formal project."""
    from ..services.novel_creation_workspace import serialize_session
    from ..services.project_creation_context import (
        project_creation_context,
        resolve_project_creation_session,
    )

    session = resolve_project_creation_session(db, project_id)
    if session is None:
        return ApiResponse.success(data={"session": None, "context": None})
    return ApiResponse.success(data={
        "session": serialize_session(session, include_runs=False),
        "context": project_creation_context(session),
    })


@router.post("/projects/{project_id}/creation-brief/ensure")
def ensure_project_creation_brief(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Create an editable brief for imported/legacy projects when requested."""
    from ..services.novel_creation_workspace import serialize_session
    from ..services.project_creation_context import (
        ensure_project_creation_session,
        project_creation_context,
    )

    try:
        session = ensure_project_creation_session(db, project_id)
        commit_session(db)
        db.refresh(session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse.success(data={
        "session": serialize_session(session, include_runs=False),
        "context": project_creation_context(session),
    })


@router.patch("/projects/{project_id}/creation-brief")
async def patch_project_creation_brief(
    project_id: str,
    payload: ProjectCreationBriefPatchRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """Save visible creation constraints, direction and style for a formal work."""
    from ..services.workspace.tools.projects import update_project_creation_brief

    result = await update_project_creation_brief(
        db,
        project_id,
        payload.model_dump(exclude_none=True),
    )
    status = str(result.get("status") or "error")
    detail = str(result.get("detail") or "立项资料保存失败")
    if status == "needs_confirmation":
        db.rollback()
        raise HTTPException(status_code=409, detail=detail)
    if status != "ok":
        db.rollback()
        raise HTTPException(
            status_code=404 if detail == "未找到作品" else 400,
            detail=detail,
        )
    commit_session(db)
    return ApiResponse.success(data=result["data"], message=detail)


@router.put("/projects/{project_id}", response_model=ApiResponse[ProjectResponse])
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    workspace: Annotated[ProjectWorkspace, Depends(get_project_workspace)],
    command: Annotated[StoryCommandContext, Depends(get_story_command)],
):
    result = workspace.update(project_id, payload.model_dump(exclude_unset=True))
    command.queue_all(result.sync_intents)
    command.finish()
    return ApiResponse.success(data=result.data, message="作品更新成功")


@router.get("/projects/{project_id}/storage/health")
def get_project_storage_health(
    project_id: str,
    workspace: Annotated[ProjectWorkspace, Depends(get_project_workspace)],
):
    return ApiResponse.success(data=workspace.storage_health(project_id))


@router.post("/projects/{project_id}/storage/repair")
async def repair_project_storage(
    project_id: str,
    payload: ProjectStorageRepairRequest,
    workspace: Annotated[ProjectWorkspace, Depends(get_project_workspace)],
    command: Annotated[StoryCommandContext, Depends(get_story_command)],
):
    data = await workspace.repair_storage(project_id, payload.action)
    if data.get("tool_status") == "ok":
        command.finish()
    else:
        command.rollback()
    data["storage_health"] = workspace.storage_health(project_id)
    return ApiResponse.success(data=data, message=str(data.get("tool_detail") or "success"))


@router.delete("/projects/{project_id}", response_model=ApiResponse[None])
def delete_project(
    project_id: str,
    workspace: Annotated[ProjectWorkspace, Depends(get_project_workspace)],
    command: Annotated[StoryCommandContext, Depends(get_story_command)],
):
    result = workspace.delete(project_id)
    command.queue_all(result.sync_intents)
    command.finish()
    return ApiResponse.success(message="作品已删除")
