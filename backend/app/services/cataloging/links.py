"""Relationship/link write helpers for cataloging."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ...database.models import (
    Chapter,
    ChapterCharacter,
    ChapterWorldbuilding,
    Character,
    OutlineNode,
    OutlineNodeCharacter,
    WorldbuildingEntry,
)
from ...modules.continuity.domain.cataloging_contract import (
    CHAPTER_CHARACTER_APPEARANCE_TYPES,
)
from ...modules.continuity.domain.outline_character_contract import outline_character_ids


def link_chapter_character(
    db: Session,
    chapter: Chapter,
    character: Character,
    *,
    appearance_type: str,
    description: str,
) -> None:
    normalized_type = str(appearance_type or "").strip()
    if normalized_type not in CHAPTER_CHARACTER_APPEARANCE_TYPES:
        raise ValueError(
            "章节人物关联 appearance_type 必须是："
            + "、".join(sorted(CHAPTER_CHARACTER_APPEARANCE_TYPES))
        )
    existing = db.query(ChapterCharacter).filter(
        ChapterCharacter.chapter_id == chapter.id,
        ChapterCharacter.character_id == character.id,
    ).first()
    if existing:
        existing.appearance_type = normalized_type
        if description:
            existing.description = description[:2000]
        return
    db.add(ChapterCharacter(
        chapter_id=chapter.id,
        character_id=character.id,
        appearance_type=normalized_type,
        description=description[:2000],
    ))


def link_chapter_worldbuilding(db: Session, chapter: Chapter, entry: WorldbuildingEntry, description: str) -> None:
    existing = db.query(ChapterWorldbuilding).filter(
        ChapterWorldbuilding.chapter_id == chapter.id,
        ChapterWorldbuilding.worldbuilding_entry_id == entry.id,
    ).first()
    if existing:
        if description:
            existing.description = description[:2000]
        return
    db.add(ChapterWorldbuilding(
        chapter_id=chapter.id,
        worldbuilding_entry_id=entry.id,
        description=description[:2000],
    ))


def resolve_outline_characters(db: Session, project_id: str, character_ids: Any) -> list[Character]:
    ids = outline_character_ids({"character_ids": character_ids})
    by_id = {row.id: row for row in db.query(Character).filter(
        Character.project_id == project_id, Character.id.in_(ids),
    ).all()}
    missing = [value for value in ids if value not in by_id]
    if missing:
        raise ValueError("大纲 character_ids 不属于当前作品角色：" + "、".join(missing))
    return [by_id[value] for value in ids]


def link_outline_characters(
    db: Session,
    project_id: str,
    node: OutlineNode,
    character_ids: Any,
    *,
    replace: bool = False,
) -> None:
    if node.project_id != project_id:
        raise ValueError("大纲人物绑定目标不属于当前作品")
    characters = resolve_outline_characters(db, project_id, character_ids)
    wanted_ids = {character.id for character in characters}
    if replace:
        # Scene nodes created by cataloging are a current-version projection.
        # Planned chapter nodes remain author-owned and continue using additive
        # links, but a retained scene must not keep characters removed by a
        # later rewrite of the same chapter.
        for link in list(node.linked_characters):
            if link.character_id not in wanted_ids:
                node.linked_characters.remove(link)
                db.delete(link)
    existing_ids = {link.character_id for link in node.linked_characters}
    for character in characters:
        if character.id not in existing_ids:
            node.linked_characters.append(
                OutlineNodeCharacter(character_id=character.id, role_in_scene="建档关联")
            )
            existing_ids.add(character.id)
