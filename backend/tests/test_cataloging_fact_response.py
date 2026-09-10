"""Do not report a complete archive after dropping partially parsed facts."""

import asyncio
import json

import httpx
import pytest

from app.database.models import CatalogingCandidate, CatalogingFact, CatalogingJob
from app.services.cataloging import launcher, orchestrator
from app.services.cataloging.fact_store import SOURCE_FACT_TYPES
from app.services.cataloging.facts import parse_fact_response
from tests.test_cataloging_progress import catalog as catalog_fixture
from tests.test_cataloging_progress import model_rows

catalog = catalog_fixture
FACTS = [
    {"fact_type": "chapter_overview", "payload": {"summary": "完整核验。"}},
    {"fact_type": "outline_fact", "payload": {"title_hint": "核验", "summary": "逐项核对。"}},
]


@pytest.mark.parametrize(
    "shape", ["jsonl", "comma_lines", "array", "pretty", "wrapped", "mixed", "fenced"]
)
def test_every_valid_fact_survives_structural_framing(shape):
    rows = [json.dumps(f, ensure_ascii=False) for f in FACTS]
    text = {
        "jsonl": "\n".join(rows),
        "comma_lines": ",\n\n".join(rows) + ",",
        "array": json.dumps(FACTS),
        "pretty": json.dumps(FACTS, indent=2),
        "wrapped": json.dumps({"facts": FACTS}, indent=2),
        "mixed": rows[0] + "\n" + json.dumps(FACTS[1], indent=2),
        "fenced": "```jsonl\n" + ",\n".join(rows) + "\n```",
    }[shape]
    facts = parse_fact_response(text)
    assert [(f["fact_type"], f["payload"]) for f in facts] == [
        (f["fact_type"], f["payload"]) for f in FACTS
    ]


@pytest.mark.parametrize(
    "bad", ['{"fact_type":', '{"fact_type":"unknown"}', "null", "说明文字", ",{}"]
)
def test_a_valid_fact_cannot_hide_an_invalid_following_record(bad):
    with pytest.raises(ValueError):
        parse_fact_response(json.dumps(FACTS[0]) + "\n" + bad)


def test_protocol_thinking_is_removed_without_changing_tags_in_fact_fields():
    fact = {"fact_type": "chapter_overview", "payload": {"summary": "原文含<think>不能删</think>。"}}
    response = '<think>protocol only</think>\n```json\n' + json.dumps([fact]) + '\n```'
    assert parse_fact_response(response)[0]["payload"] == fact["payload"]


@pytest.mark.parametrize(
    "valid", [True, False], ids=["mixed-format-complete", "truncated-must-stop"]
)
def test_worker_validates_the_complete_response_before_candidate_generation(
    catalog, monkeypatch, valid
):
    app, sessions, job_id = catalog
    calls = []
    text = (
        json.dumps(FACTS[0]) + ",\n\n" + json.dumps(FACTS[1], indent=2)
        if valid
        else json.dumps(FACTS[0]) + '\n{"fact_type":'
    )

    async def model(messages, **kwargs):
        fact_stage = messages[0]["content"] == orchestrator.FACT_EXTRACTION_SYSTEM_PROMPT
        calls.append("facts" if fact_stage else "candidates")
        output = text if fact_stage else "\n".join(json.dumps(r) for r in model_rows())
        # Frame and Unicode boundaries do not necessarily align with chunks.
        for start in range(0, len(output), 23):
            yield output[start : start + 23]
            await asyncio.sleep(0)

    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion", model)

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(f"/projects/p/cataloging/{job_id}/retry-current")
            assert response.status_code == 200
            worker = launcher._LAUNCH_TASKS.get(job_id)
            if worker:
                await asyncio.wait_for(worker, 10)
        with sessions() as db:
            job = db.get(CatalogingJob, job_id)
            facts = db.query(CatalogingFact).filter(CatalogingFact.fact_type.in_(SOURCE_FACT_TYPES))
            if valid:
                assert job.status == "completed", job.error
                assert [r.fact_type for r in facts.order_by(CatalogingFact.sort_order)] == [
                    r["fact_type"] for r in FACTS
                ]
                assert calls == ["facts", "candidates"]
            else:
                assert job.status == "paused_on_failure"
                assert facts.count() == 0  # Partial rows cannot be reused on a resolution retry.
                assert db.query(CatalogingCandidate).count() == 0
                assert calls == ["facts", "facts", "facts"]

    asyncio.run(check())
