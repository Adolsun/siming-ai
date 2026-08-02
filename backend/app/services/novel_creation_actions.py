"""Cycle-free wiring for entity edits and artifact restoration."""
from __future__ import annotations

from typing import Any

from app.services.novel_creation_authoring import _validate_stage
from app.services.novel_creation_entities import (
    delete_creation_entity as _delete_creation_entity,
    patch_creation_entity as _patch_creation_entity,
)
from app.services.novel_creation_versions import restore_artifact_version as _restore_artifact_version
from app.services.novel_creation_workspace import patch_creation_artifact, save_stage, serialize_creation_artifact


def patch_creation_entity(session: Any, entity: Any, changes: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    return _patch_creation_entity(
        session, entity, changes, patcher=patch_creation_artifact, validator=_validate_stage, **kwargs,
    )


def delete_creation_entity(session: Any, entity: Any, **kwargs: Any) -> dict[str, Any]:
    return _delete_creation_entity(
        session, entity, patcher=patch_creation_artifact, validator=_validate_stage, **kwargs,
    )


def restore_artifact_version(session: Any, version: Any, **kwargs: Any) -> dict[str, Any]:
    return _restore_artifact_version(
        session,
        version,
        validator=_validate_stage,
        save_stage_fn=save_stage,
        serialize_artifact_fn=serialize_creation_artifact,
        **kwargs,
    )
