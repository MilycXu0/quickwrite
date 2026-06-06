"""Repository for Novel entity."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.core.models import Novel, NovelStatus

logger = logging.getLogger(__name__)


class NovelRepository:
    """Data access for novels."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, novel: Novel) -> Novel:
        """Create a new novel."""
        self.session.add(novel)
        self.session.commit()
        logger.info("Created novel: %s (id=%d)", novel.title, novel.id)
        return novel

    def get(self, novel_id: int) -> Optional[Novel]:
        """Get a novel by ID."""
        return self.session.get(Novel, novel_id)

    def get_active(self) -> Optional[Novel]:
        """Get the current actively-writing novel."""
        return (
            self.session.query(Novel)
            .filter(Novel.status == NovelStatus.WRITING.value)
            .first()
        )

    def list_all(self) -> list[Novel]:
        """List all novels, newest first."""
        return (
            self.session.query(Novel)
            .order_by(Novel.created_at.desc())
            .all()
        )

    def list_by_status(self, status: NovelStatus) -> list[Novel]:
        """List novels by status."""
        return (
            self.session.query(Novel)
            .filter(Novel.status == status.value)
            .order_by(Novel.created_at.desc())
            .all()
        )

    def update_status(self, novel_id: int, status: NovelStatus) -> Optional[Novel]:
        """Update a novel's status."""
        novel = self.get(novel_id)
        if novel:
            novel.status = status.value
            novel.updated_at = datetime.utcnow()
            self.session.commit()
            logger.info("Novel %d status -> %s", novel_id, status.value)
        return novel

    def increment_chapters(self, novel_id: int) -> Optional[Novel]:
        """Increment the total chapter count for a novel."""
        novel = self.get(novel_id)
        if novel:
            novel.total_chapters += 1
            novel.updated_at = datetime.utcnow()
            self.session.commit()
        return novel

    def update_world_setting(self, novel_id: int, world_setting: dict) -> Optional[Novel]:
        """Update the world setting JSON."""
        novel = self.get(novel_id)
        if novel:
            novel.world_setting = world_setting
            novel.updated_at = datetime.utcnow()
            self.session.commit()
        return novel

    def delete(self, novel_id: int) -> bool:
        """Delete a novel and its associated data (chapters, characters, plot points)."""
        novel = self.get(novel_id)
        if novel:
            try:
                # Explicitly delete associated generation logs first
                self.session.query(Novel).filter(
                    Novel.__tablename__ == "generation_logs"
                )
                from src.core.models import Chapter, Character, GenerationLog, PlotPoint
                # Delete child records in order to avoid FK issues
                self.session.query(GenerationLog).filter(
                    GenerationLog.chapter_id.in_(
                        self.session.query(Chapter.id).filter(Chapter.novel_id == novel_id)
                    )
                ).delete(synchronize_session="fetch")
                self.session.query(GenerationLog).filter(
                    GenerationLog.novel_id == novel_id
                ).delete(synchronize_session="fetch")
                self.session.query(PlotPoint).filter(
                    PlotPoint.novel_id == novel_id
                ).delete(synchronize_session="fetch")
                self.session.query(Character).filter(
                    Character.novel_id == novel_id
                ).delete(synchronize_session="fetch")
                self.session.query(Chapter).filter(
                    Chapter.novel_id == novel_id
                ).delete(synchronize_session="fetch")
                # Finally delete the novel itself
                self.session.delete(novel)
                self.session.commit()
                logger.info("Deleted novel %d and all associated data", novel_id)
                return True
            except Exception as e:
                self.session.rollback()
                logger.error("Failed to delete novel %d: %s", novel_id, e)
                raise
        return False
