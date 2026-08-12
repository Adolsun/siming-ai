"""Narrow tool scope used by the conversational creation Agent.

This module is intentionally dependency-free so both the in-process assistant
and the MCP permission registry can share one allowlist without creating an
import cycle.
"""

from __future__ import annotations

CREATION_AGENT_TOOL_NAMES = frozenset({
    "get_creation_session",
    "get_creation_snapshot",
    "get_creation_operation",
    "get_creation_artifact",
    "list_creation_artifacts",
    "get_creation_dependencies",
    "get_creation_dependency_graph",
    "validate_creation_consistency",
    "patch_creation_session",
    "patch_creation_artifact",
    "lock_creation_fields",
    "unlock_creation_fields",
    "undo_creation_artifact",
    "list_creation_entities",
    "get_creation_entity",
    "patch_creation_entity",
    "delete_creation_entity",
    "list_creation_artifact_versions",
    "get_creation_artifact_diff",
    "restore_creation_artifact_version",
    "confirm_creation_artifact",
    "generate_creation_artifact",
    "refine_creation_artifact",
    "regenerate_creation_artifact",
    "cancel_creation_operation",
    "pause_creation_operation",
    "resume_creation_operation",
    "retry_creation_operation",
    "validate_creation_session",
    "finalize_creation_session",
    "preview_creation_import",
    "apply_creation_import",
})


__all__ = ["CREATION_AGENT_TOOL_NAMES"]
