"""Repository for TrendingElement entity."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from src.core.models import TrendingElement

logger = logging.getLogger(__name__)


class TrendRepository:
    """Data access for trending elements."""

    def __init__(self, session: Session):
        self.session = session

    def save_batch(self, elements: list[TrendingElement]) -> list[TrendingElement]:
        """Save a batch of trending elements, replacing old data from same source."""
        # Delete old entries for the sources being updated
        if elements:
            sources = {e.source for e in elements}
            for source in sources:
                self.session.query(TrendingElement).filter(
                    TrendingElement.source == source
                ).delete()
            self.session.add_all(elements)
            self.session.commit()
            logger.info("Saved %d trending elements", len(elements))
        return elements

    def get_top_tags(self, source: Optional[str] = None, limit: int = 20) -> list[TrendingElement]:
        """Get the most frequent tags, optionally filtered by source."""
        q = self.session.query(TrendingElement).filter(TrendingElement.category == "tag")
        if source:
            q = q.filter(TrendingElement.source == source)
        return q.order_by(TrendingElement.frequency.desc()).limit(limit).all()

    def get_recent(self, hours: int = 24) -> list[TrendingElement]:
        """Get elements collected within the last N hours."""
        since = datetime.utcnow() - timedelta(hours=hours)
        return (
            self.session.query(TrendingElement)
            .filter(TrendingElement.collected_at >= since)
            .order_by(TrendingElement.frequency.desc())
            .all()
        )

    def get_by_source(self, source: str) -> list[TrendingElement]:
        """Get all trending elements from a specific source."""
        return (
            self.session.query(TrendingElement)
            .filter(TrendingElement.source == source)
            .order_by(TrendingElement.frequency.desc())
            .all()
        )
