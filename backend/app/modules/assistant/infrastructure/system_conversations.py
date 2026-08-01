"""SQLAlchemy system-assistant conversation adapter."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ....core.exceptions import NotFoundError
from .models import SystemAssistantConversation, SystemAssistantMessage


def _title_from_message(message: str) -> str:
    title = " ".join((message or "").strip().split())
    if not title:
        return "新对话"
    return title[:36] + ("..." if len(title) > 36 else "")


def _conversation_data(
    conversation: SystemAssistantConversation,
    message_count: int | None = None,
) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "scope": "system",
        "message_count": message_count,
        "creation_session_id": conversation.creation_session_id,
        "user_brief": conversation.user_brief,
        "blueprints": conversation.blueprint_json or [],
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
    }


def _message_data(message: SystemAssistantMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content,
        "run_id": message.run_id,
        "operation_id": message.operation_id,
        "message_type": message.message_type,
        "payload": message.payload_json,
        "status": message.status,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "updated_at": message.updated_at.isoformat() if message.updated_at else None,
    }


class SqlAlchemySystemConversationStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _conversation(self, conversation_id: str) -> SystemAssistantConversation:
        conversation = (
            self._session.query(SystemAssistantConversation)
            .filter(SystemAssistantConversation.id == conversation_id)
            .first()
        )
        if not conversation:
            raise NotFoundError("系统助手对话不存在")
        return conversation

    def list(self) -> dict[str, Any]:
        conversations = (
            self._session.query(SystemAssistantConversation)
            .order_by(
                SystemAssistantConversation.updated_at.desc(),
                SystemAssistantConversation.created_at.desc(),
            )
            .all()
        )
        counts = dict(
            self._session.query(
                SystemAssistantMessage.conversation_id,
                func.count(SystemAssistantMessage.id),
            )
            .group_by(SystemAssistantMessage.conversation_id)
            .all()
        )
        items = [
            _conversation_data(conversation, int(counts.get(conversation.id, 0)))
            for conversation in conversations
        ]
        return {"items": items, "total": len(items)}

    def create(self, title: str) -> dict[str, Any]:
        conversation = SystemAssistantConversation(title=title.strip() or "新对话")
        self._session.add(conversation)
        self._session.flush()
        return {"conversation": _conversation_data(conversation, 0)}

    def get(self, conversation_id: str) -> dict[str, Any]:
        conversation = self._conversation(conversation_id)
        messages = (
            self._session.query(SystemAssistantMessage)
            .filter(SystemAssistantMessage.conversation_id == conversation.id)
            .order_by(
                SystemAssistantMessage.created_at.asc(),
                SystemAssistantMessage.role.desc(),
                SystemAssistantMessage.updated_at.asc(),
                SystemAssistantMessage.id.asc(),
            )
            .all()
        )
        return {
            "conversation": _conversation_data(conversation, len(messages)),
            "messages": [_message_data(message) for message in messages],
        }

    def start_turn(
        self,
        conversation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a user turn and its running assistant placeholder."""
        conversation = self._conversation(conversation_id)
        if conversation.title == "新对话":
            conversation.title = _title_from_message(str(payload.get("user_content") or ""))
        for field, source in (("creation_session_id", "creation_session_id"), ("user_brief", "user_brief")):
            if payload.get(source) is not None:
                setattr(conversation, field, payload.get(source) or None)

        user_message = SystemAssistantMessage(
            conversation_id=conversation.id,
            role="user",
            content=payload["user_content"],
            status="completed",
        )
        assistant_message = SystemAssistantMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="",
            run_id=payload.get("run_id"),
            operation_id=payload.get("operation_id"),
            message_type=payload.get("message_type") or "text",
            status="running",
            payload_json=payload.get("payload"),
        )
        self._session.add_all([user_message, assistant_message])
        self._session.flush()
        return {
            "conversation": _conversation_data(conversation),
            "messages": [_message_data(user_message), _message_data(assistant_message)],
        }

    def finish_turn(
        self,
        conversation_id: str,
        assistant_message_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Finish or fail a previously persisted assistant placeholder."""
        conversation = self._conversation(conversation_id)
        message = self._session.query(SystemAssistantMessage).filter(
            SystemAssistantMessage.id == assistant_message_id,
            SystemAssistantMessage.conversation_id == conversation.id,
            SystemAssistantMessage.role == "assistant",
        ).first()
        if not message:
            raise NotFoundError("系统助手消息不存在")
        message.content = payload.get("assistant_content") or ""
        message.status = payload.get("status") or "completed"
        if payload.get("run_id") is not None:
            message.run_id = payload.get("run_id") or None
        if payload.get("operation_id") is not None:
            message.operation_id = payload.get("operation_id") or None
        if payload.get("message_type") is not None:
            message.message_type = payload.get("message_type") or "text"
        message.payload_json = payload.get("payload")
        if payload.get("creation_session_id") is not None:
            conversation.creation_session_id = payload.get("creation_session_id") or None
        if payload.get("user_brief") is not None:
            conversation.user_brief = payload.get("user_brief") or None
        if payload.get("blueprints") is not None:
            conversation.blueprint_json = payload["blueprints"]
        self._session.flush()
        return {"conversation": _conversation_data(conversation), "message": _message_data(message)}

    def interrupt_running_messages(self) -> int:
        """Make abandoned placeholders explicit and recoverable after restart."""
        messages = self._session.query(SystemAssistantMessage).filter(
            SystemAssistantMessage.role == "assistant",
            SystemAssistantMessage.status == "running",
        ).all()
        now = datetime.utcnow()
        for message in messages:
            message.status = "interrupted"
            if not message.content.strip():
                message.content = "上次处理在应用关闭或服务重启时中断，可按原消息重试。"
            payload = dict(message.payload_json or {})
            payload["interrupted_at"] = now.isoformat()
            payload["retryable"] = True
            message.payload_json = payload
            message.updated_at = now
        if messages:
            self._session.flush()
        return len(messages)

    def append_turn(
        self,
        conversation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        conversation = self._conversation(conversation_id)
        if conversation.title == "新对话":
            conversation.title = _title_from_message(str(payload.get("user_content") or ""))
        if payload.get("creation_session_id") is not None:
            conversation.creation_session_id = payload.get("creation_session_id") or None
        if payload.get("user_brief") is not None:
            conversation.user_brief = payload.get("user_brief") or None
        if payload.get("blueprints") is not None:
            conversation.blueprint_json = payload["blueprints"]

        user_message = SystemAssistantMessage(
            conversation_id=conversation.id,
            role="user",
            content=payload["user_content"],
            status="completed",
        )
        assistant_message = SystemAssistantMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=payload.get("assistant_content") or "",
            status=payload.get("status") or "completed",
            payload_json=payload.get("payload"),
        )
        self._session.add_all([user_message, assistant_message])
        self._session.flush()
        return {
            "conversation": _conversation_data(conversation),
            "messages": [_message_data(user_message), _message_data(assistant_message)],
        }

    def delete(self, conversation_id: str) -> dict[str, Any]:
        self._session.delete(self._conversation(conversation_id))
        self._session.flush()
        return {"id": conversation_id}


__all__ = ["SqlAlchemySystemConversationStore"]
