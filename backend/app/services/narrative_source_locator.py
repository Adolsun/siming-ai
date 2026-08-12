"""Verified source ranges for narrative-governance records."""
from __future__ import annotations

import re
from typing import Any


_PUNCT_OR_SPACE = re.compile(r"[\s，。！？；：、“”‘’（）()【】\[\]《》<>…—·,.!?;:'\"-]+")
_QUOTE = re.compile(r"[“「『\"]([^”」』\"]{6,})[”」』\"]")
_STOP_CHARS = set("的了是在和与及将把被为有中上下一这那其本章故事人物事情已经进行需要必须仍然一个")


def _normalize_with_map(value: str) -> tuple[str, list[int]]:
    text: list[str] = []
    indexes: list[int] = []
    for index, char in enumerate(value or ""):
        normalized = char.casefold()
        if _PUNCT_OR_SPACE.fullmatch(normalized):
            continue
        text.append(normalized)
        indexes.append(index)
    return "".join(text), indexes


def _fragments(evidence: str) -> list[str]:
    source = str(evidence or "").strip()
    values = {source} if source else set()
    values.update(match.group(1).strip() for match in _QUOTE.finditer(source))
    values.update(
        re.sub(r"^\s*(?:原文|证据|依据|正文|章节中|文中)\s*[：:]\s*", "", part).strip()
        for part in re.split(r"[\r\n]+|(?<=[。！？；!?;])", source)
    )
    return sorted((item for item in values if len(item) >= 6), key=len, reverse=True)


def _exact_range(content: str, fragment: str) -> tuple[int, int] | None:
    start = content.find(fragment)
    if start >= 0:
        return start, start + len(fragment)
    normalized_content, indexes = _normalize_with_map(content)
    normalized_fragment, _ = _normalize_with_map(fragment)
    if len(normalized_fragment) < 6:
        return None
    normalized_start = normalized_content.find(normalized_fragment)
    if normalized_start < 0:
        return None
    start = indexes[normalized_start]
    end = indexes[normalized_start + len(normalized_fragment) - 1] + 1
    return start, end


def _segments(content: str) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    for paragraph in re.finditer(r"[^\r\n]+", content or ""):
        raw = paragraph.group(0)
        if len(raw.strip()) < 6:
            continue
        # A paragraph is a useful visual target. Extremely long paragraphs are
        # split into sentences so selection remains precise.
        if len(raw) <= 500:
            result.append((paragraph.start(), paragraph.end(), raw))
            continue
        for sentence in re.finditer(r"[^。！？!?]+[。！？!?]?", raw):
            if len(sentence.group(0).strip()) >= 6:
                result.append((
                    paragraph.start() + sentence.start(),
                    paragraph.start() + sentence.end(),
                    sentence.group(0),
                ))
    return result


def _signal_chars(value: str) -> set[str]:
    normalized, _ = _normalize_with_map(value)
    return {char for char in normalized if char not in _STOP_CHARS}


def resolve_narrative_source_range(
    content: str,
    *,
    evidence: str = "",
    hints: list[Any] | tuple[Any, ...] = (),
) -> dict[str, Any] | None:
    """Return an exact character range or a conservative hint-derived range."""

    if not content:
        return None
    for fragment in _fragments(evidence):
        found = _exact_range(content, fragment)
        if found:
            start, end = found
            return {
                "source_excerpt": content[start:end],
                "source_char_start": start,
                "source_char_end": end,
                "source_locator_method": "evidence_exact",
                "source_locator_confidence": 1.0,
            }

    query = " ".join(str(item or "").strip() for item in (evidence, *hints) if str(item or "").strip())
    query_chars = _signal_chars(query)
    if len(query_chars) < 3:
        return None
    ranked: list[tuple[float, int, int, str]] = []
    for start, end, segment in _segments(content):
        segment_chars = _signal_chars(segment)
        overlap = len(query_chars & segment_chars)
        if overlap < 3:
            continue
        coverage = overlap / len(query_chars)
        precision = overlap / max(1, min(len(segment_chars), len(query_chars) * 2))
        score = (coverage * 0.72) + (precision * 0.28)
        ranked.append((score, start, end, segment))
    if not ranked:
        return None
    ranked.sort(reverse=True, key=lambda item: item[0])
    score, start, end, segment = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    if score < 0.38 or (runner_up and score - runner_up < 0.06):
        return None
    return {
        "source_excerpt": segment,
        "source_char_start": start,
        "source_char_end": end,
        "source_locator_method": "hint_overlap",
        "source_locator_confidence": round(score, 3),
    }
