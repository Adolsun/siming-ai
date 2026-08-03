"""JSON repair utilities for LLM outputs."""
from __future__ import annotations

import json
import re
from typing import Optional

from ..modules.model_runtime.application.execution import model_executor as LLMGateway


def strip_json_fences(text: str) -> str:
    value = (text or "").strip().lstrip("﻿")
    # Some reasoning models expose their private reasoning as tagged text
    # before the final answer. Braces inside that section must not become the
    # start of the JSON candidate.
    value = re.sub(r"<(?:think|thinking|analysis)>[\s\S]*?</(?:think|thinking|analysis)>", "", value, flags=re.IGNORECASE).strip()
    for _ in range(2):
        if value.startswith("```json"):
            value = value[7:]
        elif value.startswith("```"):
            value = value[3:]
        if value.endswith("```"):
            value = value[:-3]
    return value.strip()


def remove_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def normalize_json_punctuation(text: str) -> str:
    return text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")


def repair_truncated_json(candidate: str) -> Optional[str]:
    """Conservatively close an object cut off by a model token limit."""
    repaired = candidate.strip()
    if not repaired.startswith("{"):
        return None
    stack: list[str] = []
    normalized: list[str] = []
    in_string = False
    escape = False
    changed = False
    for char in repaired:
        normalized.append(char)
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]":
            # Models often close the outer array/object while omitting one
            # nested object brace, e.g. ..."arguments": {...}]}. Insert only
            # the closers required to make the existing closer legal.
            while stack and stack[-1] != char:
                normalized.insert(len(normalized) - 1, stack.pop())
                changed = True
            if stack and stack[-1] == char:
                stack.pop()
    repaired = "".join(normalized)
    if not stack and not in_string and not changed:
        return None
    if in_string:
        repaired += '"'
    repaired = repaired.rstrip()
    for _ in range(3):
        next_text = re.sub(r',?\s*"[^"\\]*(?:\\.[^"\\]*)*"\s*:\s*$', "", repaired).rstrip()
        if next_text == repaired:
            break
        repaired = next_text
    repaired = re.sub(r"[:,]\s*$", "", repaired).rstrip()
    repaired += "".join(reversed(stack))
    return remove_trailing_commas(repaired)


def escape_json_string_values(text: str) -> str:
    """Escape unescaped ASCII double-quotes inside JSON string values.

    Scans the text tracking in-string / out-of-string state and escape mode.
    When a double-quote appears inside a string and is NOT followed by a JSON
    structural character (, } ] :), it is treated as an accidental unescaped
    quote (e.g. from Chinese dialogue) and escaped as \\\".
    """
    result: list[str] = []
    in_string = False
    escape_next = False
    i = 0
    while i < len(text):
        ch = text[i]
        if not in_string:
            result.append(ch)
            if ch == '"':
                in_string = True
            i += 1
        else:
            if escape_next:
                result.append(ch)
                escape_next = False
                i += 1
            elif ch == '\\':
                result.append(ch)
                escape_next = True
                i += 1
            elif ch == '"':
                ahead = i + 1
                while ahead < len(text) and text[ahead].isspace():
                    ahead += 1
                if ahead >= len(text) or text[ahead] in ',}:]':
                    in_string = False
                    result.append(ch)
                else:
                    result.append('\\')
                    result.append('"')
                i += 1
            else:
                result.append(ch)
                i += 1
    return ''.join(result)


def parse_json_object_detailed(text: str) -> tuple[Optional[dict], Optional[str]]:
    """Parse one object and report whether deterministic repair was required."""
    cleaned = strip_json_fences(text)

    def _try_parse(candidate_text: str) -> Optional[dict]:
        starts: list[int] = []
        depth = 0
        in_string = False
        escape = False
        for index, char in enumerate(candidate_text):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                if depth == 0:
                    starts.append(index)
                depth += 1
            elif char == "}" and depth > 0:
                depth -= 1
        if not starts:
            return None
        # Decode every possible object start and keep the largest valid
        # object. This skips prose/reasoning braces while preferring the final
        # top-level payload over nested objects inside it.
        decoder = json.JSONDecoder(strict=False)
        decoded: list[tuple[int, dict]] = []
        for start in starts:
            try:
                parsed, end = decoder.raw_decode(candidate_text[start:])
                if isinstance(parsed, dict):
                    decoded.append((end, parsed))
            except (json.JSONDecodeError, ValueError):
                continue
        if decoded:
            return max(decoded, key=lambda item: item[0])[1]
        return None

    parsed = _try_parse(cleaned)
    if parsed is not None:
        return parsed, "direct"
    escaped = escape_json_string_values(cleaned)
    if escaped != cleaned:
        parsed = _try_parse(escaped)
        if parsed is not None:
            return parsed, "deterministic_json"
    normalized = remove_trailing_commas(normalize_json_punctuation(cleaned))
    parsed = _try_parse(normalized)
    if parsed is not None:
        return parsed, "deterministic_json"
    start = normalized.find("{")
    if start >= 0:
        repaired = repair_truncated_json(normalized[start:])
        if repaired:
            parsed = _try_parse(repaired)
            if parsed is not None:
                return parsed, "deterministic_json"
    return None, None


def parse_json_object(text: str) -> Optional[dict]:
    parsed, _method = parse_json_object_detailed(text)
    return parsed


WORKSPACE_JSON_REPAIR_SYSTEM_PROMPT = (
    "你是JSON修复器，只修复语法，不改写正文，不增删工具动作。"
    "输入是小说项目助手返回的近似JSON，可能因为章节正文里的引号、换行或尾随文本导致无法解析。"
    "请把它修复为一个可被 json.loads 解析的合法JSON对象。"
    "必须保留 reply、done、actions、needs_confirmation 字段；actions 内的工具名和参数必须尽量原样保留。"
    "只输出JSON对象，不要Markdown，不要解释。"
)


async def repair_workspace_json_output(raw_text: str, model: Optional[str]) -> Optional[dict]:
    """Repair near-JSON workspace assistant output once before dropping actions."""
    if not raw_text.strip():
        return None
    try:
        result = await LLMGateway.chat_completion(
            messages=[
                {"role": "system", "content": WORKSPACE_JSON_REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": raw_text[:120_000]},
            ],
            model=model,
            temperature=0,
            timeout=90,
            retry=0,
        )
    except Exception:
        return None
    return parse_json_object(result.get("content", ""))
