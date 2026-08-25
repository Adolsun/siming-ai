"""Canonical character-role vocabulary shared by every write path."""
from __future__ import annotations

import re
from typing import Final


CHARACTER_ROLE_TYPES: Final[tuple[str, ...]] = (
    "protagonist",
    "supporting",
    "antagonist",
    "mentor",
    "other",
)

_ALIASES: Final[dict[str, str]] = {
    "protagonist": "protagonist",
    "primary": "protagonist",
    "lead": "protagonist",
    "main character": "protagonist",
    "主角": "protagonist",
    "主人公": "protagonist",
    "男主": "protagonist",
    "女主": "protagonist",
    "核心主角": "protagonist",
    "第一主角": "protagonist",
    "supporting": "supporting",
    "support": "supporting",
    "side character": "supporting",
    "deuteragonist": "supporting",
    "配角": "supporting",
    "重要配角": "supporting",
    "次要角色": "supporting",
    "同伴": "supporting",
    "伙伴": "supporting",
    "队友": "supporting",
    "盟友": "supporting",
    "同门": "supporting",
    "家人": "supporting",
    "亲属": "supporting",
    "父亲": "supporting",
    "母亲": "supporting",
    "爷爷": "supporting",
    "奶奶": "supporting",
    "antagonist": "antagonist",
    "villain": "antagonist",
    "rival": "antagonist",
    "反派": "antagonist",
    "反面角色": "antagonist",
    "敌人": "antagonist",
    "敌对者": "antagonist",
    "对手": "antagonist",
    "宿敌": "antagonist",
    "mentor": "mentor",
    "guide": "mentor",
    "导师": "mentor",
    "师父": "mentor",
    "师傅": "mentor",
    "老师": "mentor",
    "前辈": "mentor",
    "引路人": "mentor",
    "other": "other",
    "其他": "other",
    "路人": "other",
    "背景角色": "other",
    "工具人": "other",
}

_TOKEN_SPLIT = re.compile(r"[,，、/|;；\n\r]+")


def character_role_description(value: object) -> str:
    """Return non-enum identity details from a model's composite role value."""

    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text or text.casefold() == "merged_alias":
        return ""
    details: list[str] = []
    for raw_token in _TOKEN_SPLIT.split(text):
        token = raw_token.strip(" ()（）[]【】:'\"")
        if not token:
            continue
        folded = token.casefold()
        if folded in _ALIASES or folded in CHARACTER_ROLE_TYPES:
            continue
        if re.match(r"^(?:本书|故事)?(?:男|女)?主角(?:身份|定位)?$", token):
            continue
        if token not in details:
            details.append(token)
    return "、".join(details)


def append_character_role_description(background: object, role_value: object, *, limit: int = 8000) -> str | None:
    """Preserve identity prose that was incorrectly embedded in ``role_type``."""

    current = str(background or "").strip()
    details = character_role_description(role_value)
    if not details:
        return current[:limit] or None
    sentence = f"身份补充：{details}"
    if details in current or sentence in current:
        return current[:limit] or None
    return f"{current}\n\n{sentence}".strip()[:limit]


def normalize_character_role_type(
    value: object,
    *,
    default: str | None = "other",
) -> str | None:
    """Convert model/user prose to the persisted role enum.

    Descriptive model output such as ``主角，穿越者，陆家三岁孙女`` is
    reduced to ``protagonist``. ``merged_alias`` remains an internal sentinel
    used by the duplicate-character merge service and is deliberately kept.
    """

    text = re.sub(r"\s+", " ", str(value or "").strip()).casefold()
    if not text:
        return default
    if text == "merged_alias":
        return text
    if text in _ALIASES:
        return _ALIASES[text]

    tokens = [token.strip(" ()（）[]【】:'\"") for token in _TOKEN_SPLIT.split(text)]
    resolved = [_ALIASES[token] for token in tokens if token in _ALIASES]
    for preferred in ("protagonist", "antagonist", "mentor", "supporting", "other"):
        if preferred in resolved:
            return preferred

    # Conservative phrase recognition: never classify “主角的父亲” as the
    # protagonist merely because it contains the word 主角.
    if any(re.match(r"^(?:本书|故事)?(?:男|女)?主角(?:身份|定位)?$", token) for token in tokens):
        return "protagonist"
    for token in tokens:
        if any(label in token for label in ("反派", "敌对", "宿敌", "villain", "antagonist")):
            return "antagonist"
        if any(label in token for label in ("导师", "师父", "师傅", "引路", "mentor")):
            return "mentor"
        if any(label in token for label in ("配角", "同伴", "伙伴", "亲属", "父亲", "母亲")):
            return "supporting"
    return default
