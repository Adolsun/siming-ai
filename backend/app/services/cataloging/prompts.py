"""Prompt templates for project cataloging."""
from __future__ import annotations

from app.prompts.cataloging_source import (
    get_internal_cataloging_system_prompt as _get_internal_cataloging_system_prompt,
)


def build_cataloging_user_prompt(context: str, chapter_title: str, chapter_content: str) -> str:
    return f"""轻量上下文：
{context}

当前章节标题：{chapter_title}

当前章节正文：
{chapter_content}

请按系统规则输出 JSONL。第一行用必填骨架对象同时输出 chapter_summary 和 chapter_outline；然后输出 section 级 outline_create，之后输出角色、关系、世界观和 chapter_link。不得只返回摘要后结束。"""

CATALOGING_SYSTEM_PROMPT = _get_internal_cataloging_system_prompt()
