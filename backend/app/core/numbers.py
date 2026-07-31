"""Number parsing helpers shared by indexing, context and planning."""
from __future__ import annotations

import re
import unicodedata

MAX_CHAPTER_NUMBER = 99_999

_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "○": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_CHINESE_NUMBER_CHARS = "零〇○一二两三四五六七八九十百千万"
_NUMBER_TOKEN = rf"[0-9０-９{_CHINESE_NUMBER_CHARS}](?:[0-9０-９{_CHINESE_NUMBER_CHARS}]|\s)*?"
_EXPLICIT_CHAPTER_RE = re.compile(rf"第\s*(?P<number>{_NUMBER_TOKEN})\s*章")
_BARE_CHAPTER_RE = re.compile(rf"(?P<number>{_NUMBER_TOKEN})\s*章")
_UNMARKED_ARABIC_RE = re.compile(r"(?<!\d)(?P<number>\d{1,5})(?!\d)")


def _normalize_number_text(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or "")))


def chinese_number_to_int(text: str) -> int | None:
    """Parse Arabic digits, Chinese unit notation, or Chinese digit sequences.

    Examples include ``25``, ``二十五`` and the positional form ``二〇二五``.
    Malformed or mixed representations return ``None``.
    """
    value = _normalize_number_text(text)
    if not value:
        return None
    if value.isdigit():
        return int(value)

    if any(char not in _CHINESE_DIGITS and char not in _CHINESE_UNITS for char in value):
        return None

    # Chinese numbers without units are positional: 一〇三 -> 103, 〇七 -> 7.
    if not any(char in _CHINESE_UNITS for char in value):
        return int("".join(str(_CHINESE_DIGITS[char]) for char in value))

    total = 0
    section = 0
    number: int | None = None
    last_small_unit = 10_000
    seen_wan = False
    for char in value:
        if char in _CHINESE_DIGITS:
            digit = _CHINESE_DIGITS[char]
            # In unit notation consecutive significant digits are malformed.
            # A zero is a placeholder, as in 一百零三.
            if number is not None and (number != 0 or digit == 0):
                return None
            if digit == 0 and total == 0 and section == 0 and number is None:
                return None
            number = digit
            continue

        unit = _CHINESE_UNITS[char]
        if unit == 10000:
            if seen_wan:
                return None
            base = section + (number or 0)
            if base == 0:
                base = 1
            total += base * unit
            section = 0
            number = None
            last_small_unit = 10_000
            seen_wan = True
        else:
            if unit >= last_small_unit or number == 0:
                return None
            section += (number if number is not None else 1) * unit
            number = None
            last_small_unit = unit
    if number == 0:
        return None
    return total + section + (number or 0)


def parse_chapter_number(value: str, *, maximum: int = MAX_CHAPTER_NUMBER) -> int | None:
    """Parse and validate a chapter number token.

    Chapter zero, negative values, malformed tokens and values above ``maximum``
    are rejected.
    """
    number = chinese_number_to_int(value)
    if number is None or number <= 0 or number > maximum:
        return None
    return number


def extract_chapter_number(
    text: str,
    *,
    allow_bare: bool = False,
    allow_unmarked: bool = False,
    maximum: int = MAX_CHAPTER_NUMBER,
) -> int | None:
    """Extract a validated chapter number from text.

    Explicit ``第…章`` forms always win.  ``allow_bare`` additionally accepts
    forms such as ``151章``. ``allow_unmarked`` preserves legacy imported-title
    ordering by accepting an otherwise unmarked Arabic number.
    """
    value = unicodedata.normalize("NFKC", str(text or ""))
    patterns = [_EXPLICIT_CHAPTER_RE]
    if allow_bare:
        patterns.append(_BARE_CHAPTER_RE)
    if allow_unmarked:
        patterns.append(_UNMARKED_ARABIC_RE)
    for pattern in patterns:
        for match in pattern.finditer(value):
            number = parse_chapter_number(match.group("number"), maximum=maximum)
            if number is not None:
                return number
    return None
