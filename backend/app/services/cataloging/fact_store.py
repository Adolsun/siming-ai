"""Serialize historical cataloging audit facts."""
from __future__ import annotations

import json
from typing import Any


from ...database.models import CatalogingFact


def fact_to_dict(row: CatalogingFact) -> dict[str, Any]:
    try:
        payload = json.loads(row.raw_payload)
    except Exception:
        payload = {}
    return {
        "id": row.id,
        "job_id": row.job_id,
        "chapter_run_id": row.chapter_run_id,
        "chapter_id": row.chapter_id,
        "fact_type": row.fact_type,
        "payload": payload if isinstance(payload, dict) else {},
        "confidence": row.confidence,
        "evidence": row.evidence,
        "sort_order": row.sort_order,
        "status": row.status,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
