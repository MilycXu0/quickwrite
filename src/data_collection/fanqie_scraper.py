"""Fanqie Novel (番茄小说) scraper.

Scrapes book metadata from public ranking and search APIs.
Fanqie uses internal JSON APIs — no HTML parsing needed for metadata.
Content decoding (charset.json cipher) is implemented for future use.

Ethical: Only scrapes publicly visible metadata (tags, categories, popularity
metrics). Does NOT scrape full novel text for reproduction.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fake_useragent import UserAgent

from src.data_collection.base import BaseScraper, ScrapedBook, ScrapeResult
from src.data_collection.rate_limiter import RateLimitConfig, RateLimiter

logger = logging.getLogger(__name__)


class FanqieScraper(BaseScraper):
    """Scrapes book metadata from fanqienovel.com public APIs.

    Known API endpoints (from open-source research):
    - Search: /api/search?query=X&offset=0&page_count=20
    - Book detail: /api/book/{book_id}
    - Category list: /api/category/{category_id}?offset=0&limit=50
    - Rankings: /api/rank/{rank_type}?offset=0&limit=50

    Rate limit: 50-150ms between requests (configurable).
    """

    BASE_URL = "https://fanqienovel.com"
    API_BASE = "https://fanqienovel.com/api"

    # Known ranking types
    RANK_TYPES = {
        "hotsales": "hotsales",      # 热销榜
        "recommend": "recommend",     # 推荐榜
        "newbooks": "newbooks",       # 新书榜
        "trending": "trending",       # 热搜榜
    }

    # Known category IDs (approximate mapping)
    CATEGORIES = {
        "玄幻": 1,
        "都市": 2,
        "仙侠": 3,
        "科幻": 4,
        "历史": 5,
        "游戏": 6,
        "悬疑": 7,
        "言情": 8,
    }

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        cache_ttl_hours: int = 6,  # Refresh more frequently for trending
        rate_limiter: Optional[RateLimiter] = None,
    ):
        super().__init__(source="fanqie", cache_dir=cache_dir, cache_ttl_hours=cache_ttl_hours)
        self.rate_limiter = rate_limiter or RateLimiter()
        self.rate_limiter.configure(
            "fanqienovel.com",
            RateLimitConfig(min_delay_ms=50, max_delay_ms=2000, backoff_base=2.0),
        )
        self._ua = UserAgent()
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
                headers=self._build_headers(),
                follow_redirects=True,
            )
        return self._client

    def _build_headers(self) -> dict:
        return {
            "User-Agent": self._ua.random,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://fanqienovel.com/",
            "Origin": "https://fanqienovel.com",
            "Connection": "keep-alive",
        }

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Main Scraping Methods ────────────────────────────

    async def scrape_ranking(self, list_type: str = "hotsales", limit: int = 50) -> ScrapeResult:
        """Scrape a ranking list from Fanqie.

        Args:
            list_type: One of "hotsales", "recommend", "newbooks", "trending".
            limit: Max books to return.

        Returns:
            ScrapeResult with book metadata.
        """
        # Check cache first
        cached = self._load_cache(list_type)
        if cached:
            return cached

        logger.info("Scraping Fanqie %s (limit=%d)", list_type, limit)

        books = []
        errors = []

        try:
            client = await self._get_client()

            # Try multiple approaches for getting book data
            # Approach 1: Category-based search
            for genre, category_id in list(self.CATEGORIES.items())[:5]:  # Top categories
                try:
                    batch = await self._scrape_category(category_id, genre, min(20, limit - len(books)))
                    books.extend(batch)
                    if len(books) >= limit:
                        break
                except Exception as e:
                    logger.warning("Failed to scrape category %s: %s", genre, e)
                    errors.append(f"category_{genre}: {e}")

            # Approach 2: Search for popular keywords
            if len(books) < limit:
                try:
                    batch = await self._scrape_search("系统流", min(20, limit - len(books)))
                    books.extend(batch)
                except Exception as e:
                    errors.append(f"search: {e}")

            # Deduplicate by book_id
            seen = set()
            unique_books = []
            for b in books:
                if b.book_id not in seen:
                    seen.add(b.book_id)
                    b.rank = len(unique_books) + 1
                    unique_books.append(b)
            books = unique_books[:limit]

        except Exception as e:
            logger.error("Fanqie scraping failed: %s", e)
            errors.append(str(e))

        result = ScrapeResult(
            source="fanqie",
            books=books,
            scraped_at=datetime.utcnow(),
            list_type=list_type,
            error="; ".join(errors) if errors else None,
        )

        if books:
            self._save_cache(result)
            logger.info("Fanqie scraped: %d books", len(books))

        return result

    async def _scrape_category(self, category_id: int, genre: str, limit: int) -> list[ScrapedBook]:
        """Scrape books from a specific category."""
        books = []
        client = await self._get_client()

        for offset in range(0, limit, 10):
            async with self.rate_limiter.acquire("fanqienovel.com"):
                try:
                    response = await client.get(
                        f"/api/category/{category_id}",
                        params={"offset": offset, "limit": min(10, limit - offset)},
                    )
                    if response.status_code == 200:
                        data = response.json()
                        items = data.get("data", {}).get("books", [])
                        for item in items:
                            book = self._parse_book(item)
                            book.genre = genre
                            books.append(book)
                        if len(items) < 10:
                            break  # No more books
                    elif response.status_code == 429:
                        self.rate_limiter.report_rate_limited("fanqienovel.com")
                    else:
                        logger.debug("Category API returned %d for cat=%d offset=%d",
                                     response.status_code, category_id, offset)
                        break
                except httpx.RequestError as e:
                    logger.warning("Request error for category %d: %s", category_id, e)
                    break

        return books

    async def _scrape_search(self, keyword: str, limit: int) -> list[ScrapedBook]:
        """Scrape books from a search query."""
        books = []
        client = await self._get_client()

        async with self.rate_limiter.acquire("fanqienovel.com"):
            try:
                response = await client.get(
                    "/api/search",
                    params={"query": keyword, "offset": 0, "page_count": limit},
                )
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("data", {}).get("books", [])
                    for item in items:
                        books.append(self._parse_book(item))
            except Exception as e:
                logger.warning("Search API error: %s", e)

        return books

    # ── Parsing ──────────────────────────────────────────

    def _parse_book(self, raw_data: dict) -> ScrapedBook:
        """Parse Fanqie API response into normalized ScrapedBook.

        Expected fields:
        - book_id, title, author, category, subcategory, tags
        - word_count, chapter_count, status, read_count, description
        """
        return ScrapedBook(
            source="fanqie",
            book_id=str(raw_data.get("book_id", raw_data.get("id", ""))),
            title=raw_data.get("title", raw_data.get("book_name", "")),
            author=raw_data.get("author", raw_data.get("author_name", "未知")),
            genre=raw_data.get("category", raw_data.get("category_name", "")),
            subgenre=raw_data.get("subcategory", raw_data.get("sub_category", "")),
            tags=self._extract_tags(raw_data),
            word_count=int(raw_data.get("word_count", raw_data.get("total_word_count", 0))),
            chapter_count=int(raw_data.get("chapter_count", raw_data.get("total_chapter_num", 0))),
            status=self._normalize_status(raw_data.get("status", raw_data.get("book_status", ""))),
            read_count=int(raw_data.get("read_count", raw_data.get("all_read_count", 0))),
            rating=float(raw_data.get("rating", raw_data.get("score", 0))) / 10.0,
            synopsis=raw_data.get("description", raw_data.get("intro", ""))[:500],
            url=f"https://fanqienovel.com/book/{raw_data.get('book_id', '')}",
        )

    def _extract_tags(self, raw_data: dict) -> list[str]:
        """Extract tags from various possible fields."""
        tags = []
        # Direct tags field
        if "tags" in raw_data and isinstance(raw_data["tags"], list):
            tags.extend(t.get("name", t) if isinstance(t, dict) else str(t)
                       for t in raw_data["tags"])
        # Labels/keywords
        if "labels" in raw_data and isinstance(raw_data["labels"], list):
            tags.extend(str(l) for l in raw_data["labels"])
        if "keywords" in raw_data and isinstance(raw_data["keywords"], list):
            tags.extend(str(k) for k in raw_data["keywords"])
        return tags[:20]

    @staticmethod
    def _normalize_status(status: str) -> str:
        status_lower = str(status).lower()
        if any(w in status_lower for w in ["完结", "completed", "finished"]):
            return "completed"
        if any(w in status_lower for w in ["连载", "ongoing", "serializing"]):
            return "ongoing"
        return str(status)

    # ── Content Decoding (for future use) ────────────────

    @staticmethod
    def decode_content(encrypted_text: str, charset: dict[str, str]) -> str:
        """Decode Fanqie's character-substitution cipher for chapter content.

        Fanqie encrypts chapter content by replacing characters according
        to a charset.json mapping table. This method reverses the substitution.

        Args:
            encrypted_text: The encoded chapter content.
            charset: Decoding map loaded from charset.json.

        Returns:
            Decoded plain text.
        """
        result = []
        for char in encrypted_text:
            result.append(charset.get(char, char))
        return "".join(result)
