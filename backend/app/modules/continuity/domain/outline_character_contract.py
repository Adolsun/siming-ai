"""Explicit character identities for outline writes; display names never select targets."""
from __future__ import annotations

from typing import Any


def outline_character_ids(payload: dict[str, Any]) -> list[str]:
    if "related_characters" in payload:
        raise ValueError("related_characters 已停用；请读取角色目录并返回 character_ids 数组")
    value = payload.get("character_ids")
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError("大纲必须显式提供 character_ids 字符串数组；无已建档人物时填写 []")
    if len(value) != len(set(value)):
        raise ValueError("character_ids 不得重复")
    return list(value)
