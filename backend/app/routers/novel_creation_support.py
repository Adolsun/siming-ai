"""Small HTTP projections kept out of the novel-creation route catalog."""
from __future__ import annotations

from typing import Any

from app.core.response import ApiResponse
from app.services.novel_creation_confirmation import ConfirmationDecision, assess_creation_confirmation
from app.services.novel_creation_workspace import serialize_session


def idempotent_confirmation_response(
    session: Any,
    stage: str,
    *,
    data: Any,
    confirm: bool,
) -> tuple[ConfirmationDecision, ApiResponse | None]:
    decision = assess_creation_confirmation(session, stage, requested_data=data, confirm=confirm)
    response = ApiResponse.success(
        data=serialize_session(session), message="当前内容已经确认",
    ) if decision.action == "already_confirmed" else None
    return decision, response
