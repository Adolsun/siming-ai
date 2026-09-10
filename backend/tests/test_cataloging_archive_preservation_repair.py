"""Recover punctuation-only archive mistakes without losing old or new facts."""
import asyncio
import json

import pytest

from app.database.models import CatalogingCandidate
from app.services.cataloging import orchestrator
from app.services.cataloging.applier import apply_candidates_for_run
from app.services.cataloging.candidate_retry import candidate_issue
from app.services.cataloging.candidate_store import create_candidate_from_raw
from app.services.workspace.tools.external_cataloging import save_external_cataloging_candidates
from tests.test_cataloging_candidate_repair import summary_payload
from tests.test_cataloging_character_targets import archive as archive_fixture

archive = archive_fixture


@pytest.mark.parametrize("field", ["items_or_assets", "background"])
def test_punctuation_rejection_exposes_the_actual_field_and_required_old_text(archive, field):
    db, _, character, job, run = archive
    original = "旧回执与只读副本。"
    setattr(character, field, original)
    db.commit()
    raw = {
        "type": "character_update" if field == "background" else "character_state_update",
        "id": character.id, "name": character.name, f"{field}_before": original,
        field: original[:-1] + "；本章新增：签字附注纸。",
    }
    rejected = create_candidate_from_raw(db, job, run, raw, 0)
    assert "首个差异在第 9 个字符" in rejected["error"]
    assert "原值 '。'，新值 '；'" in rejected["error"]
    assert candidate_issue(rejected)["repair_context"] == {
        "target_id": character.id, "field": field, "expected_value": original,
        "requirement": "preserve_and_append",
    }
    assert getattr(character, field) == original
    assert db.query(CatalogingCandidate).count() == 0

    # The MCP/CLI boundary must return the same actionable error, not discard it.
    run.status = "facts_saved"
    db.commit()
    result = asyncio.run(save_external_cataloging_candidates(db, run.project_id, {
        "job_id": job.id, "chapter_id": run.chapter_id, "candidates": [raw],
    }))
    assert result["status"] == "skipped"
    issue = result["data"]["candidate_errors"][0]
    assert issue["repair_context"] == candidate_issue(rejected)["repair_context"]
    assert issue["rejected_candidate"] == raw
    assert db.query(CatalogingCandidate).count() == 0


@pytest.mark.parametrize("field,size", [("items_or_assets", 2200), ("background", 12500)])
def test_apply_keeps_exact_cumulative_archive_beyond_former_write_limits(archive, field, size):
    db, _, character, job, run = archive
    original = " \n" + "旧" * size + "末尾。 \n"
    incoming = original + "本章新增：签字附注纸。 \n"
    setattr(character, field, original)
    db.commit()
    raw = {
        "type": "character_update" if field == "background" else "character_state_update",
        "id": character.id, "name": character.name, f"{field}_before": original, field: incoming,
    }
    result = create_candidate_from_raw(db, job, run, raw, 0)
    assert "candidate" in result, result
    events = apply_candidates_for_run(db, job, run)
    assert events[0]["type"] == "candidate_applied", events
    db.commit()
    db.expire_all()
    assert getattr(character, field) == incoming
    # Re-applying the same accepted candidate must not append it again.
    assert apply_candidates_for_run(db, job, run) == []
    assert getattr(character, field) == incoming


def test_staged_model_corrects_punctuation_using_retry_feedback(archive, monkeypatch):
    db, chapter, character, job, run = archive
    original = "旧回执与只读副本。"
    character.items_or_assets = original
    chapter.content = "主角取得签字附注纸。"
    db.commit()
    calls = []
    retained = set()

    async def stream(messages, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            yield json.dumps({"fact_type": "chapter_overview", "payload": {
                "summary": chapter.content,
            }}, ensure_ascii=False) + "\n"
            return
        state = {
            "type": "character_state_update", "id": character.id, "name": character.name,
            "items_or_assets_before": original,
            "items_or_assets": original[:-1] + "；本章新增：签字附注纸。",
        }
        if len(calls) == 2:
            rows = [
                {"type": "chapter_summary", "payload": summary_payload(characters=[character.name])},
                {"type": "outline_create", "title": chapter.title, "node_type": "chapter", "summary": chapter.content},
                {"type": "chapter_link", "characters": [{"name": character.name, "appearance_type": "出场"}]},
                state,
            ]
        else:
            assert len(calls) == 3
            prompt = messages[1]["content"]
            assert '"requirement":"preserve_and_append"' in prompt
            assert '"field":"items_or_assets"' in prompt
            assert '"expected_value":"' + original + '"' in prompt
            assert "首个差异在第 9 个字符" in prompt
            retained.update(row.id for row in db.query(CatalogingCandidate))
            assert len(retained) == 3
            state["items_or_assets"] = original + "本章新增：签字附注纸。"
            rows = [state]
        yield "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)

    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion", stream)

    async def run_stages():
        async for _ in orchestrator._extract_run(db, job, run):
            pass
        assert run.status == "awaiting_confirmation", run.error
        assert character.items_or_assets == original
        async for _ in orchestrator._apply_run(db, job, run):
            pass

    asyncio.run(run_stages())
    assert run.status in {"completed", "completed_with_warnings"}, run.error
    assert run.error is None
    assert character.items_or_assets == original + "本章新增：签字附注纸。"
    assert retained <= {row.id for row in db.query(CatalogingCandidate)}
    assert len(calls) == 3
