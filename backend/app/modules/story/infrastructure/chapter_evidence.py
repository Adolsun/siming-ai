"""SQLAlchemy implementation of the chapter evidence read port."""

from __future__ import annotations

from .entities import Chapter


class SqlAlchemyChapterEvidenceReader:
    def get(
        self,
        session,
        *,
        project_id: str,
        chapter_id: str,
    ) -> dict | None:
        chapter = (
            session.query(Chapter)
            .filter(Chapter.id == chapter_id, Chapter.project_id == project_id)
            .first()
        )
        if chapter is None:
            return None
        return {
            "id": chapter.id,
            "project_id": chapter.project_id,
            "current_version": int(chapter.current_version or 1),
        }


__all__ = ["SqlAlchemyChapterEvidenceReader"]
