"""Stable schema and stage identifiers for the novel-creation workspace."""
from __future__ import annotations


SCHEMA_VERSION = 3
OPENING_OUTLINE_CHAPTER_COUNT = 3
# Previously saved V3 drafts may already contain a confirmed 15-chapter
# opening outline. Keep that window readable/editable instead of turning an
# upgrade into a destructive migration; all newly created drafts use 3.
LEGACY_OPENING_OUTLINE_CHAPTER_COUNT = 15
OPENING_OUTLINE_LABEL = f"前{OPENING_OUTLINE_CHAPTER_COUNT}章细纲"
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
    "opening_outline": OPENING_OUTLINE_LABEL,
    "final_review": "最终审阅",
}

# Individual artifacts can be generated without a fixed wizard order. Missing
# inputs below are quality hints, not execution blockers.
SOFT_DEPENDENCIES = {
    "constraints": (),
    "concepts": ("constraints",),
    "world_style": ("constraints", "concepts"),
    "characters": ("constraints", "concepts", "world_style"),
    "locations": ("constraints", "world_style", "characters"),
    "macro_outline": ("constraints", "concepts", "world_style", "characters", "locations"),
    "opening_outline": ("constraints", "characters", "locations", "macro_outline"),
    "final_review": STAGE_ORDER[:-1],
}

# Transitive impact graph. Existing downstream data is retained and marked
# stale; it is never deleted merely because an upstream artifact changed.
IMPACT_DEPENDENCIES = {
    "constraints": STAGE_ORDER[1:],
    "concepts": ("world_style", "characters", "locations", "macro_outline", "opening_outline", "final_review"),
    "world_style": ("characters", "locations", "macro_outline", "opening_outline", "final_review"),
    "characters": ("macro_outline", "opening_outline", "final_review"),
    "locations": ("macro_outline", "opening_outline", "final_review"),
    "macro_outline": ("opening_outline", "final_review"),
    "opening_outline": ("final_review",),
    "final_review": (),
}
