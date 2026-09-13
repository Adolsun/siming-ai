"""Merge explicitly supplied candidate deltas without changing their semantic identity."""
from __future__ import annotations

import json
from typing import Any

from app.modules.continuity.domain.cataloging_contract import (
    CHAPTER_LINK_REPLACE_FIELDS,
    CHAPTER_LINK_REPLACE_LIST_FIELDS,
)

def _merge_unique_values(existing: list[Any], incoming: list[Any]) -> list[Any]:
    merged = list(existing)
    signatures = {
        json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        for item in merged
    }
    for item in incoming:
        signature = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if signature not in signatures:
            merged.append(item)
            signatures.add(signature)
    return merged


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _merge_coverage_manifest(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Only add to an accepted manifest; a retry cannot shrink its contract."""

    merged = dict(existing)
    for key, value in incoming.items():
        old_value = merged.get(key)
        if key == "scene_count":
            merged[key] = max(_positive_int(old_value), _positive_int(value)) or value
        elif isinstance(old_value, list) and isinstance(value, list):
            merged[key] = _merge_unique_values(old_value, value)
        elif key not in merged or old_value in (None, "", [], {}):
            merged[key] = value
    return merged


def _merge_candidate_payload(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    *,
    item_type: str = "",
    _schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if item_type:
        from ...modules.continuity.domain.candidate_contract import candidate_payload_schema
        _schema = candidate_payload_schema(item_type)
    properties = (_schema or {}).get("properties", {})
    coverage_manifest_mode = (
        str(incoming.get("coverage_manifest_mode") or "").strip().lower()
        if item_type == "chapter_summary"
        else ""
    )
    if coverage_manifest_mode == "replace":
        # A managed retry may discover that the first summary listed two names
        # for one logical entity. Treat the explicit replacement as a narrow
        # control operation: keep the accepted prose and narrative ledger, and
        # replace only the complete manifest. The workspace tool validates the
        # full shape and source scene count before this reaches the store.
        merged = dict(existing)
        new_manifest = incoming.get("coverage_manifest")
        if isinstance(new_manifest, dict):
            replacement = dict(new_manifest)
            merged["coverage_manifest"] = replacement
        for field in ("scenes", "character_bindings", "worldbuilding_bindings"):
            if field in incoming:
                merged[field] = incoming[field]
        merged.pop("coverage_manifest_mode", None)
        return merged

    chapter_link_mode = (
        str(incoming.get("chapter_link_mode") or "").strip().lower()
        if item_type == "chapter_link"
        else ""
    )
    if chapter_link_mode == "replace":
        # The workspace tool accepts this only for a one-record managed repair
        # containing every aggregate collection. Clear all identity-bearing
        # link fields first so an earlier alias or wrong endpoint cannot remain
        # active after the model explicitly corrects the record.
        missing = [
            key for key in CHAPTER_LINK_REPLACE_LIST_FIELDS
            if not isinstance(incoming.get(key), list)
        ]
        if missing:
            raise ValueError(
                "chapter_link replacement requires all aggregate list fields; "
                "missing or non-array fields: " + ", ".join(missing)
                + ". Resubmit this chapter_link with complete characters, worldbuilding_titles, "
                "locations, items, events arrays; preserve existing links, use [] only when empty."
            )
        merged = dict(existing)
        for key in CHAPTER_LINK_REPLACE_FIELDS:
            merged.pop(key, None)
        for key, value in incoming.items():
            if key != "chapter_link_mode":
                merged[key] = value
        merged.pop("chapter_link_mode", None)
        return merged

    merged = dict(existing)
    for key, value in incoming.items():
        if item_type == "chapter_summary" and key in {"scenes", "character_bindings", "worldbuilding_bindings"}:
            merged[key] = value
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_candidate_payload(merged[key], value, _schema=properties.get(key))
            continue
        if (
            item_type == "chapter_link"
            and isinstance(value, list)
            and isinstance(merged.get(key), list)
        ):
            # One run owns one aggregate chapter link, but managed CLI turns
            # send candidates in small batches.  A later repair must be able
            # to add identities that the completeness gate reports missing
            # without creating a second link or erasing fields already staged.
            merged[key] = _merge_unique_values(merged[key], value)
            continue
        # Explicit empty arrays/objects still matter when the old payload did
        # not declare the field.  Do not let a later empty value erase richer
        # data that was already staged.
        replace_invalid = False
        if key in merged and key in properties and value in (None, "", [], {}):
            from ...architecture.tool_spec import ToolInputSchemaValidationError, _validate_exported_schema
            try:
                _validate_exported_schema(properties[key], merged[key])
            except ToolInputSchemaValidationError:
                # A model-supplied []/null can repair a legacy wrong type.
                # The caller validates the incoming and final payloads; no
                # coercion or inferred replacement value is performed here.
                replace_invalid = True
        if key not in merged or value not in (None, "", [], {}) or replace_invalid:
            merged[key] = value
    if item_type == "chapter_summary":
        old_manifest = existing.get("coverage_manifest")
        new_manifest = incoming.get("coverage_manifest")
        if isinstance(old_manifest, dict) and isinstance(new_manifest, dict):
            merged["coverage_manifest"] = _merge_coverage_manifest(
                old_manifest,
                new_manifest,
            )
        # This is a write-control marker, never archival chapter metadata.
        merged.pop("coverage_manifest_mode", None)
    if item_type == "chapter_link":
        # This is a write-control marker, never chapter metadata.
        merged.pop("chapter_link_mode", None)
    return merged
