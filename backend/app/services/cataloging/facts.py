"""Audit and narrative facts derived from an applied chapter plan."""
from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy.orm import Session

from ...database.models import CatalogingCandidate, CatalogingFact, Chapter


def _identity(payload: dict[str, Any], keys: Iterable[str]) -> tuple[str, ...]:
    values: list[str] = []
    for key in keys:
        value = payload.get(key)
        if value is None:
            value = ""
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        values.append(str(value).strip())
    return tuple(values)


def record_cataloging_fact(
    db: Session,
    candidate: CatalogingCandidate,
    chapter: Chapter,
    *,
    fact_type: str,
    payload: dict[str, Any],
    identity_keys: Iterable[str] = (),
    replace_without_identity: bool = True,
) -> CatalogingFact | None:
    """Record a structured fact extracted from a candidate payload."""
    if not payload:
        return None

    identity_keys = tuple(identity_keys)
    new_identity = _identity(payload, identity_keys) if identity_keys else ()

    existing = (
        db.query(CatalogingFact)
        .filter(CatalogingFact.project_id == chapter.project_id)
        .filter(CatalogingFact.chapter_id == chapter.id)
        .filter(CatalogingFact.fact_type == fact_type)
        .filter(CatalogingFact.status == "active")
        .all()
    )
    for fact in existing:
        should_supersede = False
        if identity_keys and any(new_identity):
            try:
                old_payload = json.loads(fact.raw_payload or "{}")
            except Exception:
                old_payload = {}
            if isinstance(old_payload, dict) and _identity(old_payload, identity_keys) == new_identity:
                should_supersede = True
        elif replace_without_identity:
            should_supersede = True
        if should_supersede:
            fact.status = "superseded"

    fact = CatalogingFact(
        job_id=candidate.job_id,
        chapter_run_id=candidate.chapter_run_id,
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        fact_type=fact_type[:50],
        raw_payload=json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
        confidence=candidate.confidence,
        evidence=candidate.evidence,
        sort_order=candidate.sort_order or 0,
        status="active",
    )
    db.add(fact)
    db.flush()
    return fact
