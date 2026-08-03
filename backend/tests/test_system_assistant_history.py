"""Tests for persisted system assistant conversations."""
from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base
from app.modules.assistant.infrastructure.system_conversations import (
    SqlAlchemySystemConversationStore,
)
from app.routers.system_assistant import (
    SystemConversationCreate,
    SystemTurnCreate,
    SystemTurnFinish,
    append_system_turn,
    create_system_conversation,
    finish_system_turn,
    get_system_conversation,
    list_system_conversations,
    start_system_turn,
    set_system_conversation_scope,
    SystemConversationScopePatch,
)


def _db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_system_turn_accepts_large_creation_text_with_an_explicit_safety_limit():
    payload = SystemTurnCreate(user_content="设定" * 50_000)
    assert len(payload.user_content) == 100_000
    with pytest.raises(ValidationError):
        SystemTurnCreate(user_content="设" * 1_000_001)


def test_system_conversation_persists_messages_and_blueprint_state():
    db = _db_session()
    conversations = SqlAlchemySystemConversationStore(db)
    created = asyncio.run(create_system_conversation(
        SystemConversationCreate(title="克苏鲁新书"),
        conversations,
    ))
    conversation_id = created.data["conversation"]["id"]

    blueprints = [{
        "title": "规则怪谈：别替旧神签收",
        "protagonist": {"name": "林雾白"},
    }]
    asyncio.run(append_system_turn(
        conversation_id,
        SystemTurnCreate(
            user_content="帮我创建一本克苏鲁规则怪谈",
            assistant_content="已生成三个方案",
            creation_session_id="session-1",
            user_brief="克苏鲁+规则怪谈",
            blueprints=blueprints,
        ),
        conversations,
    ))

    detail = asyncio.run(get_system_conversation(conversation_id, conversations))
    assert detail.data["conversation"]["creation_session_id"] == "session-1"
    assert detail.data["conversation"]["blueprints"] == blueprints
    assert [item["role"] for item in detail.data["messages"]] == ["user", "assistant"]
    listing = asyncio.run(list_system_conversations(conversations))
    assert listing.data["total"] == 1
    assert listing.data["items"][0]["message_count"] == 2


def test_system_turn_persists_running_placeholder_before_completion():
    db = _db_session()
    conversations = SqlAlchemySystemConversationStore(db)
    created = asyncio.run(create_system_conversation(SystemConversationCreate(title=""), conversations))
    conversation_id = created.data["conversation"]["id"]

    started = asyncio.run(start_system_turn(
        conversation_id,
        SystemTurnCreate(user_content="先帮我整理人物设定"),
        conversations,
    ))
    assistant_message = started.data["messages"][1]
    assert started.data["messages"][0]["content"] == "先帮我整理人物设定"
    assert assistant_message["status"] == "running"

    finished = asyncio.run(finish_system_turn(
        conversation_id,
        assistant_message["id"],
        SystemTurnFinish(assistant_content="已整理为角色卡", status="completed"),
        conversations,
    ))
    assert finished.data["message"]["status"] == "completed"
    detail = asyncio.run(get_system_conversation(conversation_id, conversations))
    assert [message["status"] for message in detail.data["messages"]] == ["completed", "completed"]


def test_running_system_message_is_interrupted_after_restart():
    db = _db_session()
    conversations = SqlAlchemySystemConversationStore(db)
    created = asyncio.run(create_system_conversation(SystemConversationCreate(title=""), conversations))
    conversation_id = created.data["conversation"]["id"]

    started = asyncio.run(start_system_turn(
        conversation_id,
        SystemTurnCreate(
            user_content="生成角色",
            run_id="creation-run-1",
            message_type="operation",
        ),
        conversations,
    ))
    assert started.data["messages"][1]["run_id"] == "creation-run-1"
    assert conversations.interrupt_running_messages() == 1

    detail = asyncio.run(get_system_conversation(conversation_id, conversations))
    assistant = detail.data["messages"][1]
    assert assistant["status"] == "interrupted"
    assert assistant["message_type"] == "operation"
    assert assistant["payload"]["retryable"] is True


def test_conversation_scope_can_follow_creation_and_project_contexts():
    db = _db_session()
    conversations = SqlAlchemySystemConversationStore(db)
    created = asyncio.run(create_system_conversation(
        SystemConversationCreate(title="立项讨论", scope_type="creation", scope_id="creation-1"),
        conversations,
    ))
    conversation_id = created.data["conversation"]["id"]
    assert created.data["conversation"]["scope_type"] == "creation"
    assert created.data["conversation"]["scope_id"] == "creation-1"

    # The project FK is deliberately omitted here because this unit database has
    # no matching project. The store-level transition is covered using system scope.
    changed = asyncio.run(set_system_conversation_scope(
        conversation_id,
        SystemConversationScopePatch(scope_type="system"),
        conversations,
    ))
    assert changed.data["conversation"]["scope_type"] == "system"
    assert changed.data["conversation"]["scope_id"] is None
    listing = asyncio.run(list_system_conversations(conversations, scope_type="system"))
    assert [item["id"] for item in listing.data["items"]] == [conversation_id]
