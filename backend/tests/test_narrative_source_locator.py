from app.services.narrative_source_locator import resolve_narrative_source_range


CONTENT = "议事厅里争吵渐歇。\n特昂糖抬起头，发现石狮子眉心闪过一道细纹。\n她没有声张，只把这个异常记在心里。"


def test_exact_evidence_returns_verified_character_range() -> None:
    result = resolve_narrative_source_range(
        CONTENT,
        evidence="原文：特昂糖抬起头，发现石狮子眉心闪过一道细纹。",
    )

    assert result is not None
    assert CONTENT[result["source_char_start"]:result["source_char_end"]] == result["source_excerpt"]
    assert "石狮子眉心" in result["source_excerpt"]
    assert result["source_locator_method"] == "evidence_exact"


def test_missing_legacy_evidence_can_use_unambiguous_governance_hint() -> None:
    result = resolve_narrative_source_range(
        CONTENT,
        hints=["石狮子眉心闪过细纹的异常伏笔"],
    )

    assert result is not None
    assert "石狮子眉心" in result["source_excerpt"]


def test_ambiguous_or_weak_hint_does_not_jump_to_random_text() -> None:
    assert resolve_narrative_source_range(CONTENT, hints=["后续需要处理"]) is None
