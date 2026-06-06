"""Abstract base class for novel platform scrapers.

Defines the interface that all platform scrapers must implement.
Each scraper is responsible for extracting book metadata from
public ranking/list pages — NOT full novel text.
"""

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ScrapedBook:
    """Normalized book metadata from any platform."""
    source: str                          # "fanqie" or "qidian"
    book_id: str                         # Platform-specific book ID
    title: str
    author: str
    genre: str                           # Primary genre/category
    subgenre: str = ""                   # Sub-category
    tags: list[str] = field(default_factory=list)
    word_count: int = 0
    chapter_count: int = 0
    status: str = ""                     # "ongoing" or "completed"
    read_count: int = 0                  # Total reads/views
    rating: float = 0.0                  # 0-10 scale
    synopsis: str = ""                   # Book description
    rank: int = 0                        # Position in ranking list
    url: str = ""


@dataclass
class ScrapeResult:
    """Result of a scraping operation."""
    source: str
    books: list[ScrapedBook]
    scraped_at: datetime
    list_type: str                       # "hotsales", "ranking", "newbooks", etc.
    error: Optional[str] = None


class BaseScraper(ABC):
    """Abstract base for platform-specific scrapers.

    Subclasses must implement:
    - scrape_ranking(list_type, limit) -> ScrapeResult
    - _parse_book(raw_data) -> ScrapedBook
    """

    def __init__(
        self,
        source: str,
        cache_dir: Optional[Path] = None,
        cache_ttl_hours: int = 24,
    ):
        self.source = source
        self.cache_dir = cache_dir or Path("data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)

    @abstractmethod
    async def scrape_ranking(self, list_type: str = "hotsales", limit: int = 50) -> ScrapeResult:
        """Scrape a ranking list from the platform.

        Args:
            list_type: Type of ranking (hotsales, newbooks, trending, etc.)
            limit: Maximum number of books to scrape.

        Returns:
            ScrapeResult with book metadata.
        """
        ...

    @abstractmethod
    def _parse_book(self, raw_data: dict) -> ScrapedBook:
        """Parse raw platform data into normalized ScrapedBook."""
        ...

    # ── Caching ──────────────────────────────────────────

    def _get_cache_key(self, list_type: str) -> str:
        """Generate a cache key for a scraping operation."""
        raw = f"{self.source}:{list_type}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _load_cache(self, list_type: str) -> Optional[ScrapeResult]:
        """Load cached results if not expired."""
        cache_file = self.cache_dir / f"{self._get_cache_key(list_type)}.json"
        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            scraped_at = datetime.fromisoformat(data["scraped_at"])
            if datetime.utcnow() - scraped_at > self.cache_ttl:
                logger.debug("Cache expired for %s:%s", self.source, list_type)
                return None

            books = [ScrapedBook(**b) for b in data["books"]]
            logger.info("Loaded %d books from cache: %s:%s", len(books), self.source, list_type)
            return ScrapeResult(
                source=data["source"],
                books=books,
                scraped_at=scraped_at,
                list_type=data["list_type"],
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Corrupt cache file %s: %s", cache_file, e)
            return None

    def _save_cache(self, result: ScrapeResult) -> None:
        """Save scraping results to cache."""
        cache_file = self.cache_dir / f"{self._get_cache_key(result.list_type)}.json"
        data = {
            "source": result.source,
            "books": [
                {
                    "source": b.source,
                    "book_id": b.book_id,
                    "title": b.title,
                    "author": b.author,
                    "genre": b.genre,
                    "subgenre": b.subgenre,
                    "tags": b.tags,
                    "word_count": b.word_count,
                    "chapter_count": b.chapter_count,
                    "status": b.status,
                    "read_count": b.read_count,
                    "rating": b.rating,
                    "synopsis": b.synopsis,
                    "rank": b.rank,
                    "url": b.url,
                }
                for b in result.books
            ],
            "scraped_at": result.scraped_at.isoformat(),
            "source": result.source,
            "list_type": result.list_type,
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("Cached %d books for %s:%s", len(result.books), self.source, result.list_type)
