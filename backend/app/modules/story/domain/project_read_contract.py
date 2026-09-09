"""Bounded, explicit read windows for project settings and creation documents."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

PROJECT_INFO_FIELDS = (
    "id",
    "title",
    "description",
    "tags",
    "narrative_perspective",
    "writing_style",
    "forbidden_sentence_patterns",
    "rhetoric_guidelines",
    "short_sentences",
    "custom_style_prompt",
    "daily_word_goal",
    "storage_mode",
    "folder_path",
    "created_at",
    "updated_at",
)
PROJECT_READ_MAX_CHARS = 2000
PROJECT_OVERVIEW_CHARS = 100


def text_window(text: str, offset: int, count: int) -> tuple[str, dict[str, Any]]:
    offset = max(0, offset)
    value = text[offset : offset + count]
    end = offset + len(value)
    return value, {
        "offset_chars": offset,
        "returned_chars": len(value),
        "total_chars": len(text),
        "next_offset_chars": end if end < len(text) else None,
        "has_more": end < len(text),
    }


def project_info_page(source: Mapping[str, Any], arguments: Mapping[str, Any]) -> dict[str, Any]:
    field = str(arguments.get("field") or "")
    if field and field not in PROJECT_INFO_FIELDS:
        raise ValueError("field 不属于可读取的作品设置字段")
    fields = (
        ("id", field) if field and field != "id" else ((field,) if field else PROJECT_INFO_FIELDS)
    )
    count = max(
        1, min(int(arguments.get("max_chars") or PROJECT_READ_MAX_CHARS), PROJECT_READ_MAX_CHARS)
    )
    offset = max(0, int(arguments.get("offset_chars") or 0)) if field else 0
    data: dict[str, Any] = {}
    ranges: dict[str, Any] = {}
    for name in fields:
        value = source.get(name)
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if isinstance(value, str) and name != "id":
            size = count if field else (200 if name == "title" else PROJECT_OVERVIEW_CHARS)
            value, window = text_window(value, offset, size)
            if field or window["has_more"]:
                window["read_arguments"] = {
                    "project_id": source.get("id"),
                    "field": name,
                    "offset_chars": 0,
                    "max_chars": PROJECT_READ_MAX_CHARS,
                }
                if window["has_more"]:
                    window["next_arguments"] = {
                        "project_id": source.get("id"),
                        "field": name,
                        "offset_chars": window["next_offset_chars"],
                        "max_chars": count,
                    }
                ranges[name] = window
        data[name] = value
    return {"data": data, "field_ranges": ranges}


def creation_document_page(document: Any, arguments: Mapping[str, Any]) -> dict[str, Any]:
    pointer = str(arguments.get("path") or "")
    selected = document
    if pointer:
        if not pointer.startswith("/"):
            raise ValueError("path 必须是 JSON Pointer，以 / 开头；空字符串读取整个立项文档")
        for encoded in pointer[1:].split("/"):
            for index, character in enumerate(encoded):
                if character == "~" and (
                    index + 1 == len(encoded) or encoded[index + 1] not in "01"
                ):
                    raise ValueError("JSON Pointer 中的 ~ 只能编码为 ~0 或 ~1")
            key = encoded.replace("~1", "/").replace("~0", "~")
            try:
                if isinstance(selected, list):
                    if (
                        not key.isascii()
                        or not key.isdecimal()
                        or (len(key) > 1 and key.startswith("0"))
                    ):
                        raise ValueError("JSON Pointer 数组下标无效")
                    selected = selected[int(key)]
                else:
                    selected = selected[key]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError("立项文档中不存在该 path，请使用已返回的字段路径") from exc
    content = json.dumps(selected, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    offset = max(0, int(arguments.get("offset_chars") or 0))
    count = max(
        1, min(int(arguments.get("max_chars") or PROJECT_READ_MAX_CHARS), PROJECT_READ_MAX_CHARS)
    )
    visible, window = text_window(content, offset, count)
    result = {
        "path": pointer,
        "format": "json",
        "content": visible,
        "content_range": window,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    if window["has_more"]:
        result["next_arguments"] = {
            "path": pointer,
            "offset_chars": window["next_offset_chars"],
            "max_chars": count,
        }
    return result
