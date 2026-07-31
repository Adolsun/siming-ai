"""Deterministic chapter-writing intent predicates shared by assistant paths."""
from __future__ import annotations

import re

_STRONG_CHAPTER_WRITING_PHRASES = (
    "写章", "写一章", "写本章", "写这一章", "续写", "继续写", "开始写",
    "生成正文", "创作正文", "写正文", "创建章节", "新建章节", "生成章节",
    "重写本章", "重写这一章", "重写章节", "重写正文",
)
_REWRITE_CHAPTER_PHRASES = (
    "重写本章", "重写这一章", "重写这章", "重写章节", "重写正文",
)
_CHAPTER_TARGET = (
    r"(?:第\s*[0-9０-９零〇○一二两三四五六七八九十百千万\s]+\s*章|"
    r"[0-9０-９零〇○一二两三四五六七八九十百千万]+\s*章|本章|这一章|这章|章节|正文)"
)
_OUTLINE_ONLY_ACTION = re.compile(
    rf"(?:写|精写|重写|改写|创作|创建|新建|生成|补充|规划)\s*"
    rf"{_CHAPTER_TARGET}\s*(?:的\s*)?大纲"
)


def has_strong_chapter_writing_intent(text: str) -> bool:
    """Return whether a message clearly asks to create chapter prose."""
    value = str(text or "").strip()
    if not value:
        return False
    # Remove only actions whose target is explicitly an outline. This keeps
    # "写第一章，按照大纲来" as prose writing, while treating
    # "创建第一章大纲" as planning. Any later "生成正文" remains visible.
    prose_request = _OUTLINE_ONLY_ACTION.sub("", value)
    if any(phrase in prose_request for phrase in _STRONG_CHAPTER_WRITING_PHRASES):
        return True
    return bool(re.search(
        rf"(?:帮我|请|直接|现在|开始|用\S*模式)?\s*"
        rf"(?:写|精写|重写|改写|创作|生成|创建|新建)\s*{_CHAPTER_TARGET}",
        prose_request,
    ))


def has_chapter_rewrite_intent(text: str) -> bool:
    """Return whether a message explicitly requests replacing existing prose."""
    value = str(text or "").strip()
    if not value:
        return False
    if any(phrase in value for phrase in _REWRITE_CHAPTER_PHRASES):
        return True
    return bool(re.search(rf"(?:重写|重新写|改写)\s*{_CHAPTER_TARGET}", value))


__all__ = ["has_chapter_rewrite_intent", "has_strong_chapter_writing_intent"]
