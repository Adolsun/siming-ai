"""Generic creation dependency and entity-target generation contracts."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.novel_creation_consistency import (
    creation_dependency_graph,
    validate_creation_consistency,
)
from app.services.novel_creation_stage_execution import _merge_entity_generation
from tests.test_novel_creation_workspace_v2 import _db, _ready_session


def test_dependency_graph_covers_artifacts_entities_and_references():
    db = _db()
    session = _ready_session(db)
    graph = creation_dependency_graph(session)
    assert graph["summary"]["artifact_count"] == 8
    assert graph["summary"]["entity_count"] > 0
    assert any(edge["relation"] == "soft" for edge in graph["edges"])
    assert any(edge["relation"] == "impact" for edge in graph["edges"])
    assert any(edge["relation"] == "contains" for edge in graph["edges"])


def test_consistency_report_uses_stable_issue_codes_and_does_not_mutate():
    db = _db()
    session = _ready_session(db)
    before_revision = int(session.revision or 0)
    session.draft_json["stages"]["opening_outline"]["status"] = "stale"
    report = validate_creation_consistency(session)
    assert report["revision"] == before_revision
    assert any(issue["code"] == "stale_artifact" for issue in report["issues"])
    assert int(session.revision or 0) == before_revision


def test_entity_generation_replaces_only_the_selected_row():
    baseline = {
        "characters": [
            {"name": "主角", "goal": "守城"},
            {"name": "反派", "goal": "夺城"},
        ],
        "relationships": [],
    }
    generated = {
        "characters": [{"name": "反派", "goal": "揭开旧案", "secret": "旧案证人"}],
        "relationships": [{"source": "主角", "target": "反派"}],
    }
    context = SimpleNamespace(
        operation="refine",
        working_draft={"artifact_locks": {"characters": ["/characters/1/goal"]}},
        entity_target={
            "id": "entity-2",
            "entity_type": "character",
            "entity_key": "反派",
            "mode": "existing",
        },
    )
    merged, summary = _merge_entity_generation(context, "characters", baseline, generated)
    assert merged["characters"] == [
        {"name": "主角", "goal": "守城"},
        {"name": "反派", "goal": "夺城", "secret": "旧案证人"},
    ]
    assert merged["relationships"] == []
    assert summary["preserved_entity_count"] == 1
