"""Architecture fence: chapter writes may only enter canonical cataloging."""
from __future__ import annotations

from pathlib import Path

from app.mcp.adapter import list_mcp_tools
from app.services.workspace.registry import registry


FORBIDDEN_TOOL_NAMES = (
    "archive_chapter_" + "after_write",
    "apply_external_" + "story_updates",
)

FORBIDDEN_CHAPTER_WRITE_BYPASSES = (
    "auto_" + "cataloging",
    "disabled_by_" + "caller",
)


def test_removed_side_channel_tools_are_not_registered_or_exposed():
    for name in FORBIDDEN_TOOL_NAMES:
        assert registry.get(name) is None
        assert registry.get_spec(name) is None
    for permission_pack in (
        "readonly_collaboration",
        "project_writing",
        "project_management",
        "internal_llm",
        "trusted_local_maintenance",
    ):
        exposed = {tool.name for tool in list_mcp_tools(permission_pack=permission_pack)}
        assert exposed.isdisjoint(FORBIDDEN_TOOL_NAMES)


def test_removed_side_channel_names_cannot_reenter_runtime_or_prompts():
    repository = Path(__file__).resolve().parents[2]
    roots = (
        repository / "backend" / "app",
        repository / "backend" / "prompt_specs",
        repository / "frontend" / "src",
        repository / "scripts",
    )
    suffixes = {".py", ".md", ".ts", ".tsx", ".json", ".ps1"}
    violations: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for name in FORBIDDEN_TOOL_NAMES:
                if name in text:
                    violations.append(f"{path.relative_to(repository)}: {name}")
    assert not violations, "Removed post-write side channel was reintroduced:\n" + "\n".join(violations)


def test_chapter_write_cannot_disable_canonical_cataloging():
    repository = Path(__file__).resolve().parents[2]
    chapter_tool = repository / "backend" / "app" / "services" / "workspace" / "tools" / "chapters.py"
    text = chapter_tool.read_text(encoding="utf-8")
    for bypass in FORBIDDEN_CHAPTER_WRITE_BYPASSES:
        assert bypass not in text
