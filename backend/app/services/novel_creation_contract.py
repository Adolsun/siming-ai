"""Stable schema and stage identifiers for the novel-creation workspace."""
from __future__ import annotations


SCHEMA_VERSION = 3
STAGE_ORDER = (
    "constraints",
    "concepts",
    "world_style",
    "characters",
    "locations",
    "macro_outline",
    "opening_outline",
    "final_review",
)
STAGE_LABELS = {
    "constraints": "创作约束",
    "concepts": "创意方向",
    "world_style": "文风与世界观",
    "characters": "角色与关系",
    "locations": "地点与势力",
    "macro_outline": "全书主线与卷纲",
    "opening_outline": "前15章细纲",
    "final_review": "最终审阅",
}
