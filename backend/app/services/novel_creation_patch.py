"""Deterministic JSON Pointer parsing for creation artifact patches."""
from __future__ import annotations

from typing import Any


def pointer_parts(path: str) -> list[str]:
    if path in {"", "/"}:
        return []
    if not path.startswith("/"):
        raise ValueError(f"patch path must be a JSON Pointer: {path}")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def path_is_locked(path: str, locked_paths: list[str]) -> bool:
    normalized = path.rstrip("/") or "/"
    return any(
        normalized == lock.rstrip("/")
        or normalized.startswith(lock.rstrip("/") + "/")
        or lock.rstrip("/").startswith(normalized + "/")
        for lock in locked_paths
    )


def patch_parent(document: Any, parts: list[str]) -> tuple[Any, str]:
    if not parts:
        raise ValueError("the artifact root cannot be removed or appended")
    cursor = document
    for part in parts[:-1]:
        if isinstance(cursor, dict):
            if part not in cursor:
                cursor[part] = {}
            cursor = cursor[part]
        elif isinstance(cursor, list):
            try:
                cursor = cursor[int(part)]
            except (ValueError, IndexError) as exc:
                raise ValueError(f"invalid list path segment: {part}") from exc
        else:
            raise ValueError(f"patch path crosses a scalar value: {part}")
    return cursor, parts[-1]


def normalize_patch_operation(change: dict[str, Any]) -> tuple[str, str]:
    path = str(change.get("path") or "").strip()
    action = str(change.get("action") or "").strip()
    standard_op = str(change.get("op") or "").strip()
    if not action and standard_op == "add":
        if path.endswith("/-"):
            return path[:-2] or "/", "append"
        return path, "set"
    if not action and standard_op in {"replace", "remove"}:
        action = standard_op
    return path, action
