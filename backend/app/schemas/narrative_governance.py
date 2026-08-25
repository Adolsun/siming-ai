from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class GovernanceWriteModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GovernanceItemPayload(GovernanceWriteModel):
    type: str
    data: dict[str, Any]


class GovernanceStatusUpdate(GovernanceWriteModel):
    status: Literal["open", "fulfilled", "resolved", "deferred", "abandoned", "invalidated", "pending_review"]
    target_chapter_id: Optional[str] = None
    target_chapter_number: Optional[int] = Field(None, ge=1)
    resolved_chapter_id: Optional[str] = None
    evidence: Optional[str] = Field(None, max_length=4000)
    resolution_note: Optional[str] = Field(None, max_length=4000)
    resolution_evidence: Optional[str] = Field(None, max_length=4000)
    verification_note: Optional[str] = Field(None, max_length=4000)
    closed_by: Optional[str] = Field(None, max_length=50)


class GovernanceCandidateBatch(GovernanceWriteModel):
    chapter_id: Optional[str] = None
    mode: Literal["preview", "apply"] = "preview"
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class CheckpointCreate(GovernanceWriteModel):
    chapter_id: Optional[str] = None
    label: Optional[str] = None
    trigger_type: str = "manual"


class GovernanceReviewVerification(GovernanceWriteModel):
    evidence: str = Field(..., min_length=4, max_length=4000)


class CheckpointRestoreRequest(GovernanceWriteModel):
    confirmation: Literal["restore"]
