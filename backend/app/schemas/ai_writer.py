"""Pydantic schemas for AI writing engine endpoints."""
from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class WorkspaceAssistantRequest(BaseModel):
    """Conversational assistant for project planning modules."""

    scope: Literal["outline", "characters", "worldbuilding", "project"] = Field(..., description="Management scope")
    message: str = Field(..., min_length=1, max_length=1_000_000)
    conversation_id: Optional[str] = None
    canonical_conversation_id: Optional[str] = Field(
        None,
        description="Canonical scoped conversation ID used to reuse the internal execution thread",
    )
    creation_session_id: Optional[str] = Field(
        None,
        description="Creation data linked to this project and available to the assistant as structured context",
    )
    selected_outline_node_id: Optional[str] = None
    selected_character_id: Optional[str] = None
    selected_text: Optional[str] = Field(None, description="User-selected text in the editor")
    selected_text_chapter_id: Optional[str] = Field(None, description="Chapter ID the selected text belongs to")
    model: Optional[str] = None
    assistant_mode: Literal["quality", "fast"] = Field("fast", description="Workspace assistant controller mode")
    temperature: Optional[float] = Field(0.3, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1)
    outline_batch_count: int = Field(3, ge=1, le=12, description="Preferred number of consecutive outline chapters to plan")
    auto_apply: bool = Field(True, description="Apply tool actions proposed by the model")
    history: list[dict] = Field(default_factory=list)


class WorkspaceAssistantRunResponse(BaseModel):
    """Stable public contract for one durable workspace-assistant run."""

    run_id: str
    operation_id: Optional[str] = None
    actual_model: Optional[str] = None
    status: str

    # Compatibility aliases retained for pre-3.1 clients.
    id: str
    model: Optional[str] = None

    project_id: str
    conversation_id: Optional[str] = None
    canonical_conversation_id: Optional[str] = Field(
        None,
        description="Canonical scoped conversation ID used to reuse the internal execution thread",
    )
    assistant_message_id: Optional[str] = None
    phase: Optional[str] = None
    scope: Optional[str] = None
    assistant_mode: Optional[str] = None
    current_iteration: int = 0
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class WorkspaceAssistantRunStepResponse(BaseModel):
    id: str
    run_id: str
    step_type: str
    tool: Optional[str] = None
    status: str
    iteration: int = 0
    detail: Optional[str] = None
    error: Optional[str] = None
    attempt_no: int = 1
    retry_of_step_id: Optional[str] = None
    resolved_step_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    request: Any = None
    result: Any = None


class WorkspaceAssistantRunListResponse(BaseModel):
    items: list[WorkspaceAssistantRunResponse]
    total: int


class WorkspaceAssistantRunDetailResponse(BaseModel):
    run: WorkspaceAssistantRunResponse
    assistant_message: Optional[dict[str, Any]] = None
    steps: list[WorkspaceAssistantRunStepResponse]
