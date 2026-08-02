"""Persisted system-level assistant conversations."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core.response import ApiResponse
from ..modules.assistant.application.system_conversations import SystemConversationStore
from ..modules.assistant.interfaces.system_conversation_dependencies import (
    get_system_conversation_store,
)

router = APIRouter(tags=["system-assistant"])


class SystemConversationCreate(BaseModel):
    title: str = ""
    scope_type: Literal["system", "creation", "project"] = "system"
    scope_id: str | None = None


class SystemConversationScopePatch(BaseModel):
    scope_type: Literal["system", "creation", "project"]
    scope_id: str | None = None


class SystemTurnCreate(BaseModel):
    user_content: str = Field(min_length=1)
    assistant_content: str = ""
    status: str = "completed"
    payload: dict[str, Any] | None = None
    creation_session_id: str | None = None
    user_brief: str | None = None
    blueprints: list[dict[str, Any]] | None = None
    run_id: str | None = None
    operation_id: str | None = None
    message_type: str = "text"
    scope_type: Literal["system", "creation", "project"] | None = None
    scope_id: str | None = None
    project_id: str | None = None


class SystemTurnFinish(BaseModel):
    assistant_content: str = ""
    status: str = "completed"
    payload: dict[str, Any] | None = None
    creation_session_id: str | None = None
    user_brief: str | None = None
    blueprints: list[dict[str, Any]] | None = None
    run_id: str | None = None
    operation_id: str | None = None
    message_type: str | None = None
    scope_type: Literal["system", "creation", "project"] | None = None
    scope_id: str | None = None
    project_id: str | None = None


@router.get("/ai/system-assistant/conversations")
async def list_system_conversations(
    conversations: Annotated[
        SystemConversationStore,
        Depends(get_system_conversation_store),
    ],
    scope_type: Literal["system", "creation", "project"] | None = None,
    scope_id: str | None = None,
):
    return ApiResponse.success(data=conversations.list(scope_type=scope_type, scope_id=scope_id))


@router.post("/ai/system-assistant/conversations")
async def create_system_conversation(
    payload: SystemConversationCreate,
    conversations: Annotated[
        SystemConversationStore,
        Depends(get_system_conversation_store),
    ],
):
    return ApiResponse.success(data=conversations.create(
        payload.title,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
    ))


@router.patch("/ai/system-assistant/conversations/{conversation_id}/scope")
async def set_system_conversation_scope(
    conversation_id: str,
    payload: SystemConversationScopePatch,
    conversations: Annotated[
        SystemConversationStore,
        Depends(get_system_conversation_store),
    ],
):
    return ApiResponse.success(data=conversations.set_scope(conversation_id, payload.model_dump()))


@router.get("/ai/system-assistant/conversations/{conversation_id}")
async def get_system_conversation(
    conversation_id: str,
    conversations: Annotated[
        SystemConversationStore,
        Depends(get_system_conversation_store),
    ],
):
    return ApiResponse.success(data=conversations.get(conversation_id))


@router.post("/ai/system-assistant/conversations/{conversation_id}/turns/start")
async def start_system_turn(
    conversation_id: str,
    payload: SystemTurnCreate,
    conversations: Annotated[
        SystemConversationStore,
        Depends(get_system_conversation_store),
    ],
):
    return ApiResponse.success(
        data=conversations.start_turn(conversation_id, payload.model_dump())
    )


@router.patch("/ai/system-assistant/conversations/{conversation_id}/turns/{assistant_message_id}")
async def finish_system_turn(
    conversation_id: str,
    assistant_message_id: str,
    payload: SystemTurnFinish,
    conversations: Annotated[
        SystemConversationStore,
        Depends(get_system_conversation_store),
    ],
):
    return ApiResponse.success(
        data=conversations.finish_turn(
            conversation_id,
            assistant_message_id,
            payload.model_dump(),
        )
    )


@router.post("/ai/system-assistant/conversations/{conversation_id}/turns")
async def append_system_turn(
    conversation_id: str,
    payload: SystemTurnCreate,
    conversations: Annotated[
        SystemConversationStore,
        Depends(get_system_conversation_store),
    ],
):
    return ApiResponse.success(
        data=conversations.append_turn(conversation_id, payload.model_dump())
    )


@router.delete("/ai/system-assistant/conversations/{conversation_id}")
async def delete_system_conversation(
    conversation_id: str,
    conversations: Annotated[
        SystemConversationStore,
        Depends(get_system_conversation_store),
    ],
):
    return ApiResponse.success(data=conversations.delete(conversation_id))


__all__ = [
    "SystemConversationCreate",
    "SystemTurnCreate",
    "append_system_turn",
    "create_system_conversation",
    "delete_system_conversation",
    "get_system_conversation",
    "list_system_conversations",
    "router",
]
