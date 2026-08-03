"""JSON Schema function definitions for all workspace tools — backward-compatible layer.

Delegates to the central registry. New code should import from registry directly.
"""
from __future__ import annotations

from collections.abc import Iterable

from .registry import registry


# ── Aggregated lists (derived from registry) ────────────────────────────

# Search/read/generate/analyze tools — allowed during information-gathering rounds
SEARCH_TOOL_SCHEMAS: list[dict] = registry.get_schemas(
    tool_types={"read", "analysis", "web", "memory", "generator"},
)

# Write tools — only allowed when the assistant is ready to commit changes
WRITE_TOOL_SCHEMAS: list[dict] = registry.get_schemas(
    tool_types={"write"},
)

ALL_TOOL_SCHEMAS: list[dict] = registry.get_schemas()

# Tool-name sets for quick classification
SEARCH_TOOL_NAMES: set[str] = registry.get_names_by_type("read") | registry.get_names_by_type("analysis") | registry.get_names_by_type("web") | registry.get_names_by_type("memory") | registry.get_names_by_type("generator")
WRITE_TOOL_NAMES: set[str] = registry.get_names_by_type("write")


def build_tool_schemas(*, search_only: bool = False) -> list[dict]:
    """Return the appropriate tool schema list.

    Args:
        search_only: If True, return only search/read tools (for info-gathering rounds).
                     If False, return all tools.

    Used by the agentic loop to expose different tools at different phases.
    """
    if search_only:
        return list(SEARCH_TOOL_SCHEMAS)
    return list(ALL_TOOL_SCHEMAS)


def select_workspace_tool_names(
    *,
    scope: str,
    message: str,
    selected_text: bool = False,
) -> list[str]:
    """Return the model-visible, authorized workspace capability catalog.

    Tool availability must not depend on wording such as ``第一章`` versus
    ``第1章``. The model chooses from every internal-agent capability. Truly
    destructive tools stay excluded until explicitly authorized.
    """
    del scope, message, selected_text
    names = {
        tool.name
        for tool in registry.list_for_internal_agent()
        if tool.risk_level != "destructive"
    }
    return sorted(names)


def build_workspace_tool_schemas(tool_names: Iterable[str]) -> list[dict]:
    wanted = set(tool_names)
    schemas: list[dict] = []
    for schema in ALL_TOOL_SCHEMAS:
        name = schema.get("function", {}).get("name")
        if name in wanted:
            schemas.append(schema)
    return schemas
