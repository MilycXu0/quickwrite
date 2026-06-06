"""Repository for Chapter entity."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.core.models import Chapter, ChapterStatus

logger = logging.getLogger(__name__)


class ChapterRepository:
    """Data access for chapters."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, chapter: Chapter) -> Chapter:
        """Create a new chapter."""
        self.session.add(chapter)
        self.session.commit()
        logger.info("Created chapter: novel=%d ch=%d", chapter.novel_id, chapter.chapter_number)
        return chapter

    def upsert(self, chapter: Chapter) -> Chapter:
        """Insert or update a chapter by (novel_id, chapter_number).

        If a chapter with the same novel_id + chapter_number exists, update it.
        Otherwise, insert a new record.
        """
        existing = self.get_by_number(chapter.novel_id, chapter.chapter_number)
        if existing:
            # Update existing record
            existing.title = chapter.title
            existing.outline = chapter.outline
            existing.status = chapter.status
            existing.content_path = chapter.content_path or existing.content_path
            existing.word_count = chapter.word_count or existing.word_count
            existing.summary = chapter.summary or existing.summary
            existing.quality_score = chapter.quality_score or existing.quality_score
            existing.updated_at = datetime.utcnow()
            self.session.commit()
            logger.info("Updated chapter: novel=%d ch=%d", chapter.novel_id, chapter.chapter_number)
            return existing
        else:
            self.session.add(chapter)
            self.session.commit()
            logger.info("Created chapter: novel=%d ch=%d", chapter.novel_id, chapter.chapter_number)
            return chapter

    def get(self, chapter_id: int) -> Optional[Chapter]:
        """Get a chapter by ID."""
        return self.session.get(Chapter, chapter_id)

    def get_by_number(self, novel_id: int, chapter_number: int) -> Optional[Chapter]:
        """Get a specific chapter of a novel by chapter number."""
        return (
            self.session.query(Chapter)
            .filter(
                Chapter.novel_id == novel_id,
                Chapter.chapter_number == chapter_number,
            )
            .first()
        )

    def get_latest(self, novel_id: int) -> Optional[Chapter]:
        """Get the latest chapter (highest chapter number) for a novel."""
        return (
            self.session.query(Chapter)
            .filter(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_number.desc())
            .first()
        )

    def get_recent(self, novel_id: int, limit: int = 10) -> list[Chapter]:
        """Get the most recent N chapters, newest first."""
        return (
            self.session.query(Chapter)
            .filter(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_number.desc())
            .limit(limit)
            .all()
        )

    def update_status(self, chapter_id: int, status: ChapterStatus) -> Optional[Chapter]:
        """Update a chapter's status."""
        chapter = self.get(chapter_id)
        if chapter:
            chapter.status = status.value
            chapter.updated_at = datetime.utcnow()
            self.session.commit()
        return chapter

    def update_content(self, chapter_id: int, content_path: str, word_count: int,
                       summary: str = "", quality_score: float = 0.0) -> Optional[Chapter]:
        """Update chapter content metadata after generation."""
        chapter = self.get(chapter_id)
        if chapter:
            chapter.content_path = content_path
            chapter.word_count = word_count
            chapter.summary = summary
            chapter.quality_score = quality_score
            chapter.status = ChapterStatus.COMPLETED.value
            chapter.updated_at = datetime.utcnow()
            self.session.commit()
        return chapter

    def count_by_novel(self, novel_id: int) -> int:
        """Count chapters for a novel (including drafts)."""
        return (
            self.session.query(Chapter)
            .filter(Chapter.novel_id == novel_id)
            .count()
        )

    def list_by_novel(self, novel_id: int) -> list[Chapter]:
        """List all chapters for a novel in order."""
        return (
            self.session.query(Chapter)
            .filter(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_number.asc())
            .all()
        )
