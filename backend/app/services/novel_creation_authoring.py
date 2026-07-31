"""Author-owned constraints and stage-output validation for V3 creation."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.services.novel_creation_workspace import _requested_volume_count


class AuthorLockViolation(ValueError):
    """The model removed or rewrote an author-owned immutable requirement."""


_WORLD_STYLE_TEXT_FIELDS = ("writing_style", "world_tone", "story_structure", "pacing")
_AUTHOR_FIELD_LABELS = {
    "writing_style": "正文风格",
    "world_tone": "世界基调",
    "story_structure": "剧情结构",
    "pacing": "叙事节奏",
    "core_tone": "核心基调",
    "atmosphere": "氛围",
    "emotional_color": "情绪色彩",
    "reader_experience": "读者感受",
    "narrative_perspective": "叙事视角",
    "perspective": "叙事视角",
    "sentence_rhythm": "句式节奏",
    "language_style": "语言风格",
    "main_line": "主线结构",
    "stages": "阶段安排",
    "opening": "开篇节奏",
    "middle": "中段节奏",
    "climax": "高潮节奏",
    "summary": "摘要",
    "description": "说明",
    "content": "内容",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _author_field_label(key: Any) -> str:
    text = _text(key)
    return _AUTHOR_FIELD_LABELS.get(text, text.replace("_", " "))


def _author_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "；".join(item for item in (_author_text(entry) for entry in value) if item)
    if isinstance(value, dict):
        parts = []
        for key, child in value.items():
            child_text = _author_text(child)
            if child_text:
                parts.append(f"{_author_field_label(key)}：{child_text}")
        return "；".join(parts)
    return _text(value)


def _dict_rows(value: Any, *, name_field: str = "name") -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [deepcopy(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        rows: list[dict[str, Any]] = []
        for key, child in value.items():
            if not isinstance(child, dict):
                continue
            item = deepcopy(child)
            item.setdefault(name_field, _text(key))
            rows.append(item)
        return rows
    return []


def _dedupe_dicts(rows: list[dict[str, Any]], key_builder: Any) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: dict[Any, int] = {}
    for row in rows:
        key = key_builder(row)
        if not key:
            unique.append(deepcopy(row))
            continue
        if key in seen:
            existing = unique[seen[key]]
            for field, value in row.items():
                if existing.get(field) in (None, "", [], {}):
                    existing[field] = deepcopy(value)
            continue
        seen[key] = len(unique)
        unique.append(deepcopy(row))
    return unique


def _looks_like_cli_metadata(data: dict[str, Any]) -> bool:
    event_type = _text(data.get("type")).lower().replace("-", "_")
    part = data.get("part") if isinstance(data.get("part"), dict) else {}
    part_type = _text(part.get("type")).lower().replace("-", "_")
    metadata_types = {
        "step_start", "step_finish", "message_start", "message_finish", "tool_start", "tool_finish",
    }
    return event_type in metadata_types or part_type in metadata_types


def _stage_contract(stage: str) -> str:
    contracts = {
        "world_style": "保留 writing_style/world_tone/story_structure/pacing/style_rules/forbidden_patterns/worldbuilding/display_groups 字段；writing_style、world_tone、story_structure、pacing 必须各自是非空字符串，不得返回对象或数组；worldbuilding 使用司命六维分类。",
        "characters": "返回 characters 数组和 relationships 数组。每个角色必须含 name、role_type（主角固定为 protagonist，其余为 supporting）和 goal；并保留年龄、外貌、位置、状态，以及 profile 的 core_motivation、inner_lack、core_belief、public_persona、hidden_persona、reveal_chapter、moral_taboo、voice、action_habit、trauma_trigger。不得把 characters 改成以人名为键的对象。",
        "locations": "返回 entries 数组和 relations 数组，不得重复实体或关系。关系必须含 source_title、target_title、relation_type、description、metadata。",
        "macro_outline": "返回 story_overview、core_conflict、ending_direction、target_chapters、volumes、stage_plan；每卷必须含 title、start_chapter、end_chapter、summary；只做全书宏观结构，不展开全部章节。",
        "opening_outline": "顶层恰好返回 chapters 数组和 sections 数组：chapters 恰好15章且每章保留 client_id；每章对应2至6个 sections，所有 section 只能放在顶层 sections 数组并通过 parent_client_id 关联章节，不得嵌套在 chapter 内。section 必须含 client_id、parent_client_id 及 metadata.scene_number/purpose/location/timeline/pov_character/characters/entry_state/exit_state/emotional_residue/unresolved_actions。",
        "final_review": "返回 ready、blocking、warnings、counts。只根据证据审阅，不擅自删改上游内容。",
    }
    return contracts.get(stage, "保持输入结构，只提高具体性、一致性和可执行性。")


def _validate_stage(stage: str, data: dict[str, Any]) -> None:
    if not isinstance(data, dict) or not data:
        raise ValueError("模型没有返回可用的阶段对象")
    if _looks_like_cli_metadata(data):
        raise ValueError("模型只返回了运行状态，没有返回可用的阶段正文")
    if stage == "concepts":
        options = data.get("options")
        expected_count = len(options) if isinstance(options, list) else 0
        if expected_count not in {1, 3}:
            raise ValueError("创意方向必须包含一张作者方案或三张探索方案")
        _validate_compact_concepts(options, expected_count=expected_count)
    if stage == "world_style":
        invalid = [
            _AUTHOR_FIELD_LABELS[field]
            for field in _WORLD_STYLE_TEXT_FIELDS
            if not isinstance(data.get(field), str) or not data[field].strip()
        ]
        if invalid:
            raise ValueError("文风与世界观缺少可读文本：" + "、".join(invalid))
        if not isinstance(data.get("worldbuilding"), list) or not data["worldbuilding"]:
            raise ValueError("文风与世界观缺少可用的世界设定条目")
    if stage == "characters":
        characters = data.get("characters") if isinstance(data.get("characters"), list) else []
        if not characters:
            raise ValueError("角色与关系阶段没有返回角色数组")
        invalid = [
            _text(item.get("name")) or f"第{index + 1}个角色"
            for index, item in enumerate(characters)
            if not isinstance(item, dict)
            or not _text(item.get("role_type"))
            or not _text(item.get("goal") or item.get("current_goal"))
        ]
        if invalid:
            raise ValueError("以下角色缺少角色类型或当前目标：" + "、".join(invalid[:5]))
    if stage == "locations":
        entries = data.get("entries") if isinstance(data.get("entries"), list) else []
        relations = data.get("relations") if isinstance(data.get("relations"), list) else []
        if not entries:
            raise ValueError("地点与势力阶段没有返回实体数组")
        titles = {
            _text(item.get("title")).casefold()
            for item in entries
            if isinstance(item, dict) and _text(item.get("title"))
        }
        invalid_relations = [
            f"{_text(item.get('source_title')) or '未知起点'} → {_text(item.get('target_title')) or '未知终点'}"
            for item in relations
            if not isinstance(item, dict)
            or not _text(item.get("source_title"))
            or not _text(item.get("target_title"))
            or not _text(item.get("relation_type"))
            or _text(item.get("source_title")).casefold() not in titles
            or _text(item.get("target_title")).casefold() not in titles
        ]
        if invalid_relations:
            raise ValueError("以下地点关系缺少端点、类型或引用了不存在的实体：" + "、".join(invalid_relations[:5]))
    if stage == "macro_outline":
        missing = [
            field for field in ("story_overview", "core_conflict", "ending_direction")
            if not _text(data.get(field))
        ]
        volumes = data.get("volumes") if isinstance(data.get("volumes"), list) else []
        if missing:
            raise ValueError("全书主线与卷纲缺少：" + "、".join(missing))
        if not volumes:
            raise ValueError("全书主线与卷纲没有返回分卷规划")
        invalid_volumes = [
            _text(item.get("title")) or f"第{index + 1}卷"
            for index, item in enumerate(volumes)
            if not isinstance(item, dict)
            or not _text(item.get("summary"))
            or int(item.get("start_chapter") or 0) <= 0
            or int(item.get("end_chapter") or 0) < int(item.get("start_chapter") or 0)
        ]
        if invalid_volumes:
            raise ValueError("以下分卷缺少有效章节范围或摘要：" + "、".join(invalid_volumes[:5]))
    if stage == "opening_outline":
        _validate_opening_outline(data)


def _validate_opening_outline(data: dict[str, Any]) -> None:
    chapters = data.get("chapters") if isinstance(data.get("chapters"), list) else []
    sections = data.get("sections") if isinstance(data.get("sections"), list) else []
    if len(chapters) != 15:
        raise ValueError(f"前15章细纲必须恰好包含15章，当前为{len(chapters)}章")
    counts: dict[str, int] = {}
    for section in sections:
        if isinstance(section, dict):
            parent = _text(section.get("parent_client_id"))
            counts[parent] = counts.get(parent, 0) + 1
    invalid = [
        _text(chapter.get("title") or chapter.get("chapter_number") or chapter.get("client_id"))
        or f"第{index + 1}章"
        for index, chapter in enumerate(chapters)
        if counts.get(_text(chapter.get("client_id")), 0) not in range(2, 7)
    ]
    if invalid:
        raise ValueError("以下章节的场景数量不在2至6个之间：" + "、".join(invalid[:5]))
    required_metadata = {
        "scene_number", "purpose", "location", "timeline", "pov_character", "characters",
        "entry_state", "exit_state", "emotional_residue", "unresolved_actions",
    }
    invalid_sections = [
        _text(section.get("title") or section.get("client_id")) or f"第{index + 1}个场景"
        for index, section in enumerate(sections)
        if not isinstance(section, dict)
        or not _text(section.get("client_id"))
        or not _text(section.get("parent_client_id"))
        or not required_metadata.issubset(set(section.get("metadata") or {}))
    ]
    if invalid_sections:
        raise ValueError("以下场景缺少结构化信息：" + "、".join(invalid_sections[:5]))


def _validate_compact_concepts(
    concepts: Any,
    *,
    expected_count: int = 3,
) -> list[dict[str, Any]]:
    if not isinstance(concepts, list) or len(concepts) != expected_count:
        label = "作者方案" if expected_count == 1 else "轻量创意卡"
        raise ValueError(f"模型必须一次返回恰好{expected_count}张{label}")
    required = ("title", "logline", "world_hook", "core_conflict", "opening_hook")
    cards: list[dict[str, Any]] = []
    titles: set[str] = set()
    for index, raw in enumerate(concepts):
        if not isinstance(raw, dict):
            raise ValueError(f"第{index + 1}张创意卡不是对象")
        missing = [field for field in required if not _text(raw.get(field))]
        protagonist = raw.get("protagonist_seed")
        if not isinstance(protagonist, dict):
            missing.append("protagonist_seed")
        else:
            for field in ("identity", "goal", "lack"):
                if not _text(protagonist.get(field)):
                    missing.append(f"protagonist_seed.{field}")
        if missing:
            raise ValueError(f"第{index + 1}张创意卡缺少：{'、'.join(missing)}")
        title = _text(raw.get("title"))
        if title in titles:
            raise ValueError("三张轻量创意卡必须具有不同标题")
        titles.add(title)
        cards.append(raw)
    return cards


def _author_context(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "creation_mode": _text(draft.get("creation_mode")) or "explore",
        "author_brief": _text(draft.get("author_brief")),
        "author_outline": _text(draft.get("author_outline")),
        "locked_requirements": [
            _text(item) for item in (draft.get("locked_requirements") or []) if _text(item)
        ],
    }


def _lock_text(value: Any) -> str:
    return re.sub(
        r"[\s，。；：、,.!?！？;:‘’“”\"'（）()《》〈〉【】\[\]]+",
        "",
        _author_text(value),
    ).casefold()


def _locked_anchors(requirement: str) -> list[str]:
    requirement = _text(requirement)
    if not requirement:
        return []
    anchors: list[str] = []
    anchors.extend(re.findall(r"[“\"「『]([^”\"」』]{2,40})[”\"」』]", requirement))
    if "：" in requirement or ":" in requirement:
        tail = re.split(r"[：:]", requirement, maxsplit=1)[-1]
        if 2 <= len(_text(tail)) <= 80:
            anchors.append(_text(tail))
    match = re.search(r"^(.{2,20}?)(?:必须|不得|不可|不能)", requirement)
    if match:
        subject = _text(match.group(1)).strip("，。；：: ")
        if subject not in {"全书", "故事", "作品", "设定", "核心设定", "结局", "主角", "角色"}:
            anchors.append(subject)
    match = re.search(
        r"(?:必须(?:保留|叫|名为|是|为|包含|采用)?|不得(?:删除|改写|修改|更名)?|"
        r"不可(?:删除|改写|修改|更名)?|不能(?:删除|改写|修改|更名)?|保留)\s*(.{2,80})$",
        requirement,
    )
    if match:
        value = re.sub(
            r"(?:不得|不可|不能)?(?:删除|改写|修改|更名|改变)$",
            "",
            match.group(1),
        ).strip("，。；：: ")
        if value and not re.fullmatch(r"[0-9０-９零〇一二两三四五六七八九十百]+卷", value):
            anchors.append(value)
    unique: list[str] = []
    for anchor in anchors:
        normalized = _lock_text(anchor)
        if len(normalized) >= 2 and normalized not in {_lock_text(item) for item in unique}:
            unique.append(_text(anchor))
    return unique


def _semantic_region(value: Any, fields: tuple[str, ...]) -> str:
    if not isinstance(value, dict):
        return ""
    return _lock_text({field: value.get(field) for field in fields if field in value})


def _stage_semantic_regions(stage: str, data: dict[str, Any]) -> list[str]:
    """Return only author-facing semantic fields, grouped by their entity."""
    regions: list[str] = []
    if stage == "concepts":
        options = data.get("options") if isinstance(data.get("options"), list) else []
        for option in options:
            if not isinstance(option, dict):
                continue
            protagonist = option.get("protagonist_seed")
            regions.append(_semantic_region(
                protagonist,
                ("name", "identity", "goal", "lack", "background", "motivation"),
            ))
            regions.append(_semantic_region(
                option,
                (
                    "title", "logline", "world_hook", "core_conflict",
                    "story_engine", "opening_hook",
                ),
            ))
    elif stage == "characters":
        for character in data.get("characters") or []:
            regions.append(_semantic_region(
                character,
                (
                    "name", "identity", "role_type", "goal", "current_goal",
                    "background", "personality", "description", "profile",
                ),
            ))
        for relationship in data.get("relationships") or []:
            regions.append(_semantic_region(
                relationship,
                (
                    "source", "target", "source_name", "target_name",
                    "relationship_type", "relation_type", "description",
                ),
            ))
    elif stage == "world_style":
        regions.append(_semantic_region(
            data,
            (
                "writing_style", "world_tone", "story_structure", "pacing",
                "style_rules", "forbidden_patterns",
            ),
        ))
        for entry in data.get("worldbuilding") or []:
            regions.append(_semantic_region(
                entry,
                ("title", "dimension", "content", "description", "rules", "summary"),
            ))
    elif stage == "locations":
        for entry in data.get("entries") or []:
            regions.append(_semantic_region(
                entry,
                ("title", "dimension", "content", "description", "rules", "summary"),
            ))
        for relationship in data.get("relations") or []:
            regions.append(_semantic_region(
                relationship,
                ("source_title", "target_title", "relation_type", "description"),
            ))
    elif stage == "macro_outline":
        regions.append(_semantic_region(
            data,
            ("story_overview", "core_conflict", "ending_direction", "stage_plan"),
        ))
        for volume in data.get("volumes") or []:
            regions.append(_semantic_region(
                volume,
                ("title", "summary", "core_conflict", "ending", "goal"),
            ))
    elif stage == "opening_outline":
        for chapter in data.get("chapters") or []:
            regions.append(_semantic_region(
                chapter,
                ("title", "summary", "goal", "hook", "chapter_number", "description"),
            ))
        for section in data.get("sections") or []:
            regions.append(_semantic_region(
                section,
                ("title", "summary", "description", "metadata"),
            ))
    elif stage == "final_review":
        regions.append(_semantic_region(data, ("blocking", "warnings", "counts")))
    return [region for region in regions if region]


def _validate_author_requirements(
    stage: str,
    data: dict[str, Any],
    baseline: dict[str, Any],
    draft: dict[str, Any],
) -> None:
    author = _author_context(draft)
    requirements = author["locked_requirements"]
    requested_volumes = _requested_volume_count(draft)
    if stage == "macro_outline" and requested_volumes:
        volumes = data.get("volumes") if isinstance(data.get("volumes"), list) else []
        if len(volumes) != requested_volumes:
            raise AuthorLockViolation(
                f"作者锁定要求为 {requested_volumes} 卷，模型返回 {len(volumes)} 卷"
            )
    if not requirements:
        return
    output_regions = _stage_semantic_regions(stage, data)
    baseline_text = "".join(_stage_semantic_regions(stage, baseline))
    stage_keywords = {
        "characters": ("主角", "角色", "姓名", "名字", "身份"),
        "world_style": ("世界", "设定", "规则", "基调"),
        "locations": ("地点", "城市", "势力", "组织"),
        "macro_outline": ("主线", "核心", "冲突", "结局", "卷"),
        "opening_outline": ("开篇", "前十五章", "前15章"),
    }
    missing: list[str] = []
    for requirement in requirements:
        relevant = stage == "concepts" or any(
            keyword in requirement for keyword in stage_keywords.get(stage, ())
        )
        anchors = _locked_anchors(requirement)
        tokens = [_lock_text(anchor) for anchor in anchors if _lock_text(anchor)]
        for token in tokens:
            if token in baseline_text:
                relevant = True
        if not relevant or not tokens:
            continue
        if not any(all(token in region for token in tokens) for region in output_regions):
            absent = [
                anchor
                for anchor, token in zip(anchors, tokens)
                if not any(token in region for region in output_regions)
            ]
            missing.extend(absent or [requirement])
    if missing:
        raise AuthorLockViolation(
            "模型结果删除或改写了作者锁定内容：" + "、".join(dict.fromkeys(missing))
        )


def _safe_compact_concepts(draft: dict[str, Any]) -> list[dict[str, Any]]:
    author = _author_context(draft)
    form = draft.get("form") if isinstance(draft.get("form"), dict) else {}
    brief = author["author_brief"] or _text(form.get("brief")) or "待补充故事方案"
    locked_source = "；".join([brief, *author["locked_requirements"]])
    protagonist_match = re.search(r"(?:^|[，。；])\s*([^，。；]{2,20}?)(?:必须是|必须为|是)", locked_source)
    protagonist_name = _text(protagonist_match.group(1)) if protagonist_match else "待确认主角"
    title_seed = brief.split("。", 1)[0].split("，", 1)[0][:20] or "作者方案"
    base = {
        "title": title_seed,
        "subtitle": "依据作者原始设定整理，可继续编辑",
        "logline": brief[:120],
        "protagonist_seed": {
            "name": protagonist_name,
            "identity": locked_source[:500],
            "goal": "落实作者方案中的首要目标",
            "lack": "待作者确认",
        },
        "world_hook": locked_source[:500],
        "core_conflict": locked_source[:500],
        "story_engine": "遵循作者大纲持续推进",
        "opening_hook": "从作者指定的起点切入",
        "differentiators": author["locked_requirements"] or ["保留作者原始设定"],
        "risks": ["这是模型格式异常后的安全草稿，请在继续前检查"],
    }
    if author["creation_mode"] == "author_led":
        return [base]
    return [
        {
            **deepcopy(base),
            "title": f"{title_seed} · 方向{index}",
            "subtitle": f"安全草稿方向 {index}，请编辑后确认",
        }
        for index in range(1, 4)
    ]
