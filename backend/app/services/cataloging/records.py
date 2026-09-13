"""Validate one native cataloging record without guessing types or identities."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ...modules.continuity.domain.candidate_contract import CANDIDATE_FIELDS, validate_candidate_fields


def normalize_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    item_type = raw.get("type")
    if not isinstance(item_type, str) or item_type not in CANDIDATE_FIELDS:
        raise ValueError("候选 type 必须使用工具契约中的标准枚举")
    payload = deepcopy(raw)
    payload.pop("type")
    validate_candidate_fields(item_type, payload)
    operation = "upsert"
    if item_type.endswith("_create"):
        operation = "create"
    elif item_type.endswith("_update"):
        operation = "update"
    elif item_type == "character_merge_candidate":
        operation = "merge"
    elif item_type == "chapter_link":
        operation = "link"
    return {
        "item_type": item_type, "operation": operation,
        "target_type": None, "target_id": payload.get("id"),
        "target_name": payload.get("name") or payload.get("title"),
        "confidence": payload.get("confidence"), "evidence": payload.get("evidence"),
        "source_task": "cataloging_plan", "payload": payload,
    }
