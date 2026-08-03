"""Read-only projections for revision-conflicted creation artifacts."""
from __future__ import annotations

from typing import Any, Iterable


def artifact_conflict_projection(
    *,
    stage: str,
    stored_status: str,
    stage_runs: Iterable[Any],
    current_revision: int,
) -> dict[str, Any]:
    latest = next((run for run in reversed(list(stage_runs)) if run.stage == stage), None)
    conflict = latest if (
        latest is not None
        and latest.status == "failed"
        and latest.failure_class == "revision_conflict"
        and isinstance(latest.result_json, dict)
        and latest.result_json.get("candidate_artifact") == stage
    ) else None
    return {
        "status": "conflict" if conflict else stored_status,
        "stored_status": stored_status,
        "conflict": ({
            "run_id": conflict.id,
            "message": conflict.current_message,
            "candidate_available": True,
            "input_revision": conflict.input_revision,
            "current_revision": current_revision,
        } if conflict else None),
    }
