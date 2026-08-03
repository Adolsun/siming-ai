"""Deterministic confirmation decisions shared by REST and workspace tools."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from app.services.novel_creation_workspace import save_stage, serialize_creation_artifact


ConfirmationAction = Literal["already_confirmed", "confirm_exact"]


@dataclass(frozen=True)
class ConfirmationDecision:
    current_data: Any
    stored_status: str
    action: ConfirmationAction | None


def assess_creation_confirmation(
    session: Any,
    stage: str,
    *,
    requested_data: Any,
    confirm: bool,
) -> ConfirmationDecision:
    artifact = serialize_creation_artifact(session, stage)
    current_data = artifact.get("data")
    stored_status = artifact.get("stored_status") or artifact.get("status") or "pending"
    action: ConfirmationAction | None = None
    if confirm and stored_status == "confirmed" and (
        not isinstance(requested_data, dict) or requested_data == current_data
    ):
        action = "already_confirmed"
    elif confirm and stored_status in {"generated", "stale"} and (
        isinstance(requested_data, dict) and requested_data == current_data
    ):
        action = "confirm_exact"
    return ConfirmationDecision(current_data, stored_status, action)


def save_exact_confirmation(session: Any, stage: str, decision: ConfirmationDecision, *, source: str) -> None:
    save_stage(
        session,
        stage,
        deepcopy(decision.current_data),
        confirm=True,
        source=source,
        change_type="confirm",
    )
