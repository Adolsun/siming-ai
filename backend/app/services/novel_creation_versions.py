"""Immutable version history and deterministic diffs for creation artifacts."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.database.models_support import generate_uuid
from app.modules.creation.infrastructure.models import (
    NovelCreationArtifactVersion,
    NovelCreationSession,
)


def serialize_artifact_version(
    version: NovelCreationArtifactVersion,
    *,
    include_snapshot: bool = False,
) -> dict[str, Any]:
    data = {
        "id": version.id,
        "session_id": version.session_id,
        "artifact": version.artifact_key,
        "revision": int(version.revision or 0),
        "status": version.status,
        "source": version.source,
        "change_type": version.change_type,
        "change_summary": deepcopy(version.change_summary_json),
        "run_id": version.run_id,
        "operation_id": version.operation_id,
        "parent_version_id": version.parent_version_id,
        "restored_from_version_id": version.restored_from_version_id,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }
    if include_snapshot:
        data["snapshot"] = deepcopy(version.snapshot_json)
    return data


def record_artifact_version(
    session: NovelCreationSession,
    artifact: str,
    snapshot: dict[str, Any],
    *,
    revision: int,
    status: str,
    source: str,
    change_type: str = "save",
    change_summary: list[dict[str, Any]] | None = None,
    run_id: str | None = None,
    operation_id: str | None = None,
    restored_from_version_id: str | None = None,
) -> NovelCreationArtifactVersion:
    existing = next(
        (
            item
            for item in session.artifact_versions
            if item.artifact_key == artifact and int(item.revision or 0) == int(revision)
        ),
        None,
    )
    if existing:
        return existing
    parent = next(
        (item for item in reversed(session.artifact_versions) if item.artifact_key == artifact),
        None,
    )
    version = NovelCreationArtifactVersion(
        id=generate_uuid(),
        artifact_key=artifact,
        revision=int(revision),
        status=status,
        source=source or "unknown",
        change_type=change_type,
        snapshot_json=deepcopy(snapshot),
        change_summary_json=deepcopy(change_summary or []),
        run_id=run_id,
        operation_id=operation_id,
        parent_version_id=parent.id if parent else None,
        restored_from_version_id=restored_from_version_id,
    )
    session.artifact_versions.append(version)
    return version


def get_artifact_version(
    db: Session,
    version_id: str,
) -> NovelCreationArtifactVersion | None:
    return db.get(NovelCreationArtifactVersion, version_id)


def list_artifact_versions(
    db: Session,
    *,
    session_id: str,
    artifact: str,
    limit: int = 100,
) -> list[NovelCreationArtifactVersion]:
    return (
        db.query(NovelCreationArtifactVersion)
        .filter_by(session_id=session_id, artifact_key=artifact)
        .order_by(NovelCreationArtifactVersion.revision.desc())
        .limit(max(1, min(int(limit), 500)))
        .all()
    )


def _pointer(path: str, key: str | int) -> str:
    token = str(key).replace("~", "~0").replace("/", "~1")
    return f"{path}/{token}" if path else f"/{token}"


def json_diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            child = _pointer(path, key)
            if key not in before:
                changes.append({"path": child, "action": "add", "after": deepcopy(after[key])})
            elif key not in after:
                changes.append({"path": child, "action": "remove", "before": deepcopy(before[key])})
            else:
                changes.extend(json_diff(before[key], after[key], child))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        common = min(len(before), len(after))
        for index in range(common):
            changes.extend(json_diff(before[index], after[index], _pointer(path, index)))
        for index in range(common, len(before)):
            changes.append({"path": _pointer(path, index), "action": "remove", "before": deepcopy(before[index])})
        for index in range(common, len(after)):
            changes.append({"path": _pointer(path, index), "action": "add", "after": deepcopy(after[index])})
        return changes
    return [{"path": path or "/", "action": "replace", "before": deepcopy(before), "after": deepcopy(after)}]


def artifact_version_diff(
    db: Session,
    version: NovelCreationArtifactVersion,
    *,
    against_version_id: str | None = None,
) -> dict[str, Any]:
    against = None
    if against_version_id:
        against = get_artifact_version(db, against_version_id)
        if not against or against.session_id != version.session_id or against.artifact_key != version.artifact_key:
            raise ValueError("对比版本不属于同一立项数据")
    elif version.parent_version_id:
        against = get_artifact_version(db, version.parent_version_id)
    changes = json_diff(against.snapshot_json if against else {}, version.snapshot_json)
    return {
        "version": serialize_artifact_version(version),
        "against": serialize_artifact_version(against) if against else None,
        "changes": changes[:500],
        "change_count": len(changes),
        "truncated": len(changes) > 500,
    }


def restore_artifact_version(
    session: NovelCreationSession,
    version: NovelCreationArtifactVersion,
    *,
    expected_revision: int,
) -> dict[str, Any]:
    if version.session_id != session.id:
        raise ValueError("版本不属于当前立项会话")
    if int(session.revision or 0) != int(expected_revision):
        raise RuntimeError("revision_conflict")
    if not isinstance(version.snapshot_json, dict):
        raise ValueError("版本不包含可恢复的结构化数据")
    from app.services.novel_creation_authoring import _validate_stage
    from app.services.novel_creation_workspace import save_stage, serialize_creation_artifact

    _validate_stage(version.artifact_key, version.snapshot_json)
    save_stage(
        session,
        version.artifact_key,
        deepcopy(version.snapshot_json),
        confirm=version.status == "confirmed",
        source="history_restore",
        change_type="restore",
        change_summary=[{"restored_from_version_id": version.id, "restored_revision": version.revision}],
        restored_from_version_id=version.id,
    )
    return {
        "artifact": serialize_creation_artifact(session, version.artifact_key),
        "restored_version": serialize_artifact_version(version),
        "revision": int(session.revision or 0),
    }


__all__ = [
    "artifact_version_diff",
    "get_artifact_version",
    "json_diff",
    "list_artifact_versions",
    "record_artifact_version",
    "restore_artifact_version",
    "serialize_artifact_version",
]
