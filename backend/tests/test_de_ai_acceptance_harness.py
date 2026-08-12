"""Regression tests for the resumable de-AI acceptance harness."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.error import URLError

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run-de-ai-acceptance.py"
SPEC = importlib.util.spec_from_file_location("run_de_ai_acceptance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


def test_checkpoint_round_trip_and_identity_guard(tmp_path):
    path = tmp_path / "round.checkpoint.json"
    payload = HARNESS._new_checkpoint("第一版正文", "codex_cli:gpt-5.6-sol")
    payload["story_ledger"] = "01 [硬] 周砚进入A17。"
    payload["outputs"]["prompt-hash"] = {"content": "周砚进了A17。"}

    HARNESS._write_checkpoint(path, payload)
    restored = HARNESS._load_checkpoint(
        path,
        source="第一版正文",
        model="codex_cli:gpt-5.6-sol",
    )
    stale = HARNESS._load_checkpoint(
        path,
        source="另一版正文",
        model="codex_cli:gpt-5.6-sol",
    )

    assert restored["story_ledger"] == payload["story_ledger"]
    assert restored["outputs"]["prompt-hash"]["content"] == "周砚进了A17。"
    assert stale["story_ledger"] == ""
    assert stale["outputs"] == {}
    assert not path.with_name(f"{path.name}.tmp").exists()


def test_checkpoint_identity_includes_immutable_authority(tmp_path):
    path = tmp_path / "follow-up.checkpoint.json"
    payload = HARNESS._new_checkpoint(
        "第二轮输入",
        "codex_cli:gpt-5.6-sol",
        authority_source="首轮原文",
    )
    payload["story_ledger"] = "01 [硬] 周砚进入A17。"
    HARNESS._write_checkpoint(path, payload)

    restored = HARNESS._load_checkpoint(
        path,
        source="第二轮输入",
        model="codex_cli:gpt-5.6-sol",
        authority_source="首轮原文",
    )
    wrong_authority = HARNESS._load_checkpoint(
        path,
        source="第二轮输入",
        model="codex_cli:gpt-5.6-sol",
        authority_source="被污染的候选稿",
    )

    assert restored["story_ledger"] == payload["story_ledger"]
    assert wrong_authority["story_ledger"] == ""


def test_lineage_round_never_promotes_candidate_only_literals_to_story_facts():
    authority = "7月12日，周砚把A17钥匙交给陈禾。" * 40
    round_input = authority + "模型误加了B99标记。"
    candidate = "7月12日，A17钥匙由周砚交到陈禾手中。" * 40

    assessment = HARNESS._assess_lineage_round(
        authority,
        round_input,
        candidate,
    )

    assert assessment["accepted"] is True
    assert "B99" not in assessment["missing_protected_tokens"]


def test_lineage_round_still_rejects_near_verbatim_follow_up():
    authority = "7月12日，周砚把A17钥匙交给陈禾。" * 40
    round_input = authority.replace("把", "将")

    assessment = HARNESS._assess_lineage_round(
        authority,
        round_input,
        round_input,
    )

    assert assessment["accepted"] is False
    assert any(
        issue["code"] == "insufficient_revision"
        for issue in assessment["issues"]
    )


def test_main_keeps_one_authority_across_all_three_rounds(tmp_path, monkeypatch):
    original = "7月12日，周砚把A17钥匙交给陈禾。" * 120
    source_path = tmp_path / "source.json"
    output_path = tmp_path / "result.json"
    source_path.write_text(
        json.dumps({"source": original}, ensure_ascii=False),
        encoding="utf-8",
    )
    calls = []

    def fake_revise(_base_url, _model, round_input, **kwargs):
        calls.append({
            "round_input": round_input,
            "authority_source": kwargs["authority_source"],
            "story_ledger_override": kwargs["story_ledger_override"],
        })
        marker = len(calls)
        rewritten = original.replace("把", "将").replace(
            "交给陈禾",
            f"交至陈禾手中第{marker}轮",
        )
        return {
            "content": rewritten,
            "_story_ledger": "01 [硬] 7月12日；周砚；A17钥匙→陈禾。",
            "_fidelity_audit": {"valid": True, "passed": True, "issues": []},
            "_style_audit": {"valid": True, "passed": True, "issues": []},
        }

    monkeypatch.setattr(HARNESS, "_revise", fake_revise)
    monkeypatch.setattr(
        HARNESS,
        "_assess_lineage_round",
        lambda *_args, **_kwargs: {"accepted": True, "issues": []},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--revision-model",
            "codex_cli:gpt-5.6-sol",
            "--source-json",
            str(source_path),
            "--rounds",
            "3",
            "--output",
            str(output_path),
        ],
    )

    assert HARNESS.main() == 0
    assert len(calls) == 3
    assert all(call["authority_source"] == original for call in calls)
    assert calls[0]["round_input"] == original
    assert calls[1]["round_input"] != original
    assert calls[2]["round_input"] != original
    assert calls[0]["story_ledger_override"] == ""
    assert calls[1]["story_ledger_override"].startswith("01 [硬]")
    assert calls[2]["story_ledger_override"].startswith("01 [硬]")


def test_post_json_retries_only_transient_connection_failure(monkeypatch):
    attempts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"code":0,"data":{"content":"ok"}}'

    def fake_urlopen(_request, *, timeout):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise URLError("temporary reset")
        return Response()

    monkeypatch.setattr(HARNESS, "urlopen", fake_urlopen)
    monkeypatch.setattr(HARNESS.time, "sleep", lambda _seconds: None)

    result = HARNESS._post_json("http://siming.test", {"x": 1}, timeout=9)

    assert result == {"content": "ok"}
    assert attempts == [9, 9]


def test_checkpoint_restores_all_historical_fidelity_issues():
    cached = {
        "first": {
            "content": (
                '{"passed":false,"issues":[{"chunk":2,"kind":"added",'
                '"detail":"卷帘门操作者被擅自写死"}]}'
            ),
        },
        "second": {
            "content": (
                '{"passed":false,"issues":[{"chunk":2,"kind":"added",'
                '"detail":"卷帘门操作者被擅自写死"},{"chunk":2,'
                '"kind":"contradiction","detail":"收音机位置写错"}]}'
            ),
        },
        "passed": {"content": '{"passed":true,"issues":[]}'},
    }

    restored = HARNESS._restore_fidelity_issue_history(cached, chunk_count=3)

    assert sorted(restored) == [1]
    assert [item["detail"] for item in restored[1]] == [
        "卷帘门操作者被擅自写死",
        "收音机位置写错",
    ]


def test_detector_verdicts_are_contiguous_and_accept_ui_aliases():
    source = "甲乙丙丁戊己"

    spans = HARNESS._parse_detector_verdicts(
        "warning:2,success:2,danger:2",
        source,
    )

    assert spans == [
        {"start": 0, "end": 2, "verdict": "suspected"},
        {"start": 2, "end": 4, "verdict": "human"},
        {"start": 4, "end": 6, "verdict": "ai"},
    ]
    with pytest.raises(ValueError, match="cover 5 characters"):
        HARNESS._parse_detector_verdicts("warning:2,success:3", source)


def test_insertion_only_guard_accepts_insertions_but_rejects_rewrites():
    source = "周砚把钥匙插进去，拧了一下。"

    assert HARNESS._preserves_non_whitespace_characters(
        source,
        "周砚把塑料柄钥匙插进去，拧了一下。",
    )
    assert not HARNESS._preserves_non_whitespace_characters(
        source,
        "周砚把钥匙塞进去，拧了一下。",
    )


def test_insertion_only_guard_ignores_paragraph_whitespace_only():
    assert HARNESS._preserves_non_whitespace_characters(
        "周砚停下。\n\n陈禾回头。",
        "周砚停下。 陈禾回头。",
    )


def test_style_score_prefers_deterministically_valid_candidate_shape():
    accepted = HARNESS.assess_de_ai_revision(
        "7月12日，周砚到A17。" * 20,
        "7月12日，周砚到A17。" * 19,
        min_length_ratio=0.88,
    )
    missing = HARNESS.assess_de_ai_revision(
        "7月12日，周砚到A17。" * 20,
        "周砚到A17。" * 19,
        min_length_ratio=0.88,
    )

    assert accepted["accepted"] is True
    assert missing["accepted"] is False


def test_insertion_guard_can_measure_strict_positive_progress():
    previous = "周砚在仓库门前停下。"
    expanded = "7月12日，周砚在仓库门前停下。"

    assert HARNESS._preserves_non_whitespace_characters(previous, expanded)
    assert HARNESS._visible_length(expanded) > HARNESS._visible_length(previous)


def test_feedback_length_repair_allows_partial_insertions_to_converge():
    assert HARNESS._feedback_length_repair_attempt_limit(1) == 4
    assert HARNESS._feedback_length_repair_attempt_limit(2) == 8


def test_detector_fidelity_repair_allows_three_complete_regenerations():
    assert HARNESS._DETECTOR_FIDELITY_REPAIR_ATTEMPTS == 3


def test_feedback_style_scope_locks_detector_human_spans():
    scoped = HARNESS._scope_style_audit_to_rejected_spans(
        {
            "valid": True,
            "passed": False,
            "issues": [
                {"chunk": 1, "kind": "recap", "detail": "重复复盘"},
                {"chunk": 3, "kind": "checklist", "detail": "逐项移动"},
            ],
        },
        [0, 1],
    )

    assert scoped["passed"] is False
    assert [item["chunk"] for item in scoped["issues"]] == [1]
    assert scoped["ignored_detector_human_span_issues"][0]["chunk"] == 3


def test_rejected_only_style_audit_maps_local_chunks_back_to_source():
    mapped = HARNESS._map_local_style_audit_to_source_chunks(
        {
            "valid": True,
            "passed": False,
            "issues": [
                {"chunk": 1, "kind": "staged", "detail": "逐拍分镜"},
                {"chunk": 2, "kind": "recap", "detail": "复盘线索"},
            ],
        },
        [1, 4],
    )

    assert mapped["passed"] is False
    assert [item["chunk"] for item in mapped["issues"]] == [2, 5]
    assert mapped["audited_detector_rejected_spans_only"] is True


def test_rejected_only_style_audit_rejects_impossible_local_chunk():
    malformed = HARNESS._map_local_style_audit_to_source_chunks(
        {
            "valid": True,
            "passed": False,
            "issues": [{"chunk": 2, "kind": "staged", "detail": "x"}],
        },
        [1],
    )

    assert malformed["valid"] is False


def test_stdin_source_normalization_preserves_exact_prose():
    piped = "\ufeff周砚进门。\r\n\r\n陈禾回头。\r\n"

    assert HARNESS._normalize_stdin_source(piped) == "周砚进门。\n\n陈禾回头。"
