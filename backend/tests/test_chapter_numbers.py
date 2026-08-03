"""Regression tests for the shared chapter-number parser."""

import pytest

from app.core.numbers import (
    chinese_number_to_int,
    extract_chapter_number,
    parse_chapter_number,
)
from app.services.context_builders import _chapter_order_number
from app.services.rag.indexer import _extract_chapter_number as rag_chapter_number


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("第一章", 1),
        ("第二十五章", 25),
        ("第一百零三章", 103),
        ("第一〇三章", 103),
        ("第〇七章", 7),
        ("第 〇 七 章", 7),
        ("第００７章", 7),
        ("第1万零三章", None),
    ],
)
def test_extract_chapter_number_matrix(text: str, expected: int | None) -> None:
    assert extract_chapter_number(text) == expected


@pytest.mark.parametrize(
    "value",
    ["零", "〇", "0", "-1", "一百百", "一二十", "一百零零七", "foo", "十万"],
)
def test_parse_chapter_number_rejects_zero_malformed_and_out_of_range(value: str) -> None:
    assert parse_chapter_number(value) is None


def test_chinese_number_parser_supports_unit_and_positional_notation() -> None:
    assert chinese_number_to_int("一万二千三百四十五") == 12_345
    assert chinese_number_to_int("二〇二五") == 2025


@pytest.mark.parametrize("parser", [rag_chapter_number, _chapter_order_number])
def test_indexing_and_context_use_shared_parser(parser) -> None:
    assert parser("第一百零三章 潮汐来信") == 103
    assert parser("第〇七章 暗火") == 7
    assert parser("附录 12") == 12
