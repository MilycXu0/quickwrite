"""Qidian (起点中文网) scraper.

Scrapes book metadata from public ranking pages.
Qidian uses traditional HTML pages with CSS selectors for parsing.
Anti-crawl: WAF, CAPTCHA, cookie validation possible.

Ethical: Only scrapes publicly visible ranking/list metadata.
Does NOT scrape full novel text for reproduction.
"""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from src.data_collection.base import BaseScraper, ScrapedBook, ScrapeResult
from src.data_collection.rate_limiter import RateLimitConfig, RateLimiter

logger = logging.getLogger(__name__)


class QidianScraper(BaseScraper):
    """Scrapes book metadata from qidian.com ranking pages.

    Known ranking pages:
    - /rank/hotsales — 热销榜
    - /rank/readindex — 阅读指数榜
    - /rank/newfans — 新书榜
    - /rank/recommend — 推荐榜
    - /rank/collect — 收藏榜
    - /free/all/ — 免费小说

    Rate limit: 500-1500ms between requests (aggressive due to WAF).
    """

    BASE_URL = "https://www.qidian.com"

    RANK_PAGES = {
        "hotsales": "/rank/hotsales/",
        "readindex": "/rank/readindex/",
        "newfans": "/rank/newfans/",
        "recommend": "/rank/recommend/",
        "collect": "/rank/collect/",
    }

    # Category mapping from URL paths
    CATEGORY_IDS = {
        "玄幻": "chanId1",
        "奇幻": "chanId2",
        "武侠": "chanId3",
        "仙侠": "chanId4",
        "都市": "chanId5",
        "现实": "chanId6",
        "军事": "chanId7",
        "历史": "chanId8",
        "游戏": "chanId9",
        "体育": "chanId10",
        "科幻": "chanId11",
        "悬疑": "chanId12",
    }

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        cache_ttl_hours: int = 6,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        super().__init__(source="qidian", cache_dir=cache_dir, cache_ttl_hours=cache_ttl_hours)
        self.rate_limiter = rate_limiter or RateLimiter()
        self.rate_limiter.configure(
            "qidian.com",
            RateLimitConfig(min_delay_ms=500, max_delay_ms=5000, backoff_base=2.0, max_retries=2),
        )
        self._ua = UserAgent()
        self._client: Optional[httpx.AsyncClient] = None
        self._cookie: Optional[str] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
                headers=self._build_headers(),
                follow_redirects=True,
                http2=True,  # Qidian supports HTTP/2
            )
        return self._client

    def _build_headers(self) -> dict:
        headers = {
            "User-Agent": self._ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.qidian.com/",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie
        return headers

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Main Scraping Methods ────────────────────────────

    async def scrape_ranking(self, list_type: str = "hotsales", limit: int = 50) -> ScrapeResult:
        """Scrape a ranking list from Qidian.

        Args:
            list_type: One of "hotsales", "readindex", "newfans", "recommend", "collect".
            limit: Max books to return.

        Returns:
            ScrapeResult with book metadata.
        """
        # Check cache
        cached = self._load_cache(list_type)
        if cached:
            return cached

        logger.info("Scraping Qidian %s (limit=%d)", list_type, limit)

        books = []
        errors = []

        # Try the primary ranking page
        rank_page = self.RANK_PAGES.get(list_type, self.RANK_PAGES["hotsales"])

        try:
            client = await self._get_client()
            batch = await self._scrape_rank_page(client, rank_page, limit)
            books.extend(batch)
        except Exception as e:
            logger.warning("Qidian ranking page failed: %s", e)
            errors.append(f"rank_page: {e}")

        # If we didn't get enough books, try individual category pages
        if len(books) < limit:
            for genre, chan_id in list(self.CATEGORY_IDS.items())[:5]:
                try:
                    category_url = f"{rank_page}?{chan_id}=1"
                    batch = await self._scrape_rank_page(
                        await self._get_client(),
                        category_url,
                        min(15, limit - len(books)),
                    )
                    books.extend(batch)
                    if len(books) >= limit:
                        break
                except Exception as e:
                    logger.debug("Category %s failed: %s", genre, e)

        # Deduplicate
        seen = set()
        unique_books = []
        for b in books:
            if b.book_id not in seen:
                seen.add(b.book_id)
                b.rank = len(unique_books) + 1
                unique_books.append(b)
        books = unique_books[:limit]

        result = ScrapeResult(
            source="qidian",
            books=books,
            scraped_at=datetime.utcnow(),
            list_type=list_type,
            error="; ".join(errors) if errors else None,
        )

        if books:
            self._save_cache(result)
            logger.info("Qidian scraped: %d books", len(books))

        return result

    async def _scrape_rank_page(
        self,
        client: httpx.AsyncClient,
        page_path: str,
        limit: int,
    ) -> list[ScrapedBook]:
        """Scrape a single ranking page."""
        books = []

        for page_num in range(1, 4):  # Max 3 pages
            if len(books) >= limit:
                break

            params = {"page": page_num} if page_num > 1 else {}
            url = page_path

            async with self.rate_limiter.acquire("qidian.com"):
                try:
                    response = await client.get(url, params=params)

                    if response.status_code == 200:
                        self.rate_limiter.report_success("qidian.com")
                        soup = BeautifulSoup(response.text, "lxml")

                        # Try to find book list items
                        book_items = self._find_book_items(soup)
                        for item in book_items:
                            if len(books) >= limit:
                                break
                            try:
                                book = self._parse_book_html(item)
                                if book and book.title:
                                    books.append(book)
                            except Exception as e:
                                logger.debug("Failed to parse book item: %s", e)

                        if not book_items:
                            break  # No more results

                    elif response.status_code == 429:
                        self.rate_limiter.report_rate_limited("qidian.com")
                        logger.warning("Qidian rate limited on page %d", page_num)
                        break
                    elif response.status_code == 403:
                        logger.warning("Qidian returned 403 — possible WAF block")
                        self.rate_limiter.report_rate_limited("qidian.com")
                        break
                    else:
                        logger.debug("Qidian returned %d for %s page %d",
                                     response.status_code, page_path, page_num)
                        break

                except httpx.RequestError as e:
                    logger.warning("Request error for %s: %s", page_path, e)
                    break

                # Extra delay between pages
                await asyncio.sleep(1.0)

        return books

    def _find_book_items(self, soup: BeautifulSoup) -> list:
        """Find book list items in the HTML using multiple selector strategies."""
        # Strategy 1: Standard ranking list
        items = soup.select(".rank-list .book-list li, .rank-list li, .book-list li")
        if items:
            return items

        # Strategy 2: Book items in common containers
        items = soup.select(".book-img-text li, .all-book-list li, .book-wrap")
        if items:
            return items

        # Strategy 3: Any list items containing book links
        items = soup.select("li a[data-bid], li a[href*='/book/']")
        if items:
            return [item.parent for item in items]

        # Strategy 4: Generic book-meta blocks
        items = soup.select("[data-rid]")
        return items

    def _parse_book_html(self, element) -> Optional[ScrapedBook]:
        """Parse a BeautifulSoup element into a ScrapedBook.

        Handles various Qidian HTML structures.
        """
        # Extract book ID and URL
        link = element.select_one("a[data-bid]") or element.select_one("a[href*='/book/']")
        if not link:
            return None

        href = link.get("href", "")
        book_id = link.get("data-bid", "")
        if not book_id:
            # Extract from URL: /book/123456/
            match = re.search(r"/book/(\d+)", href)
            book_id = match.group(1) if match else ""
        if not book_id:
            return None

        # Title
        title = link.get("title", "") or link.get_text(strip=True)

        # Author
        author_elem = element.select_one(".author, .writer, a[href*='/author/'], a[href*='/writer/']")
        author = author_elem.get_text(strip=True) if author_elem else "未知"

        # Genre/category
        genre_elem = element.select_one(".cat, .category, .type, a[href*='/category/']")
        genre = genre_elem.get_text(strip=True) if genre_elem else ""

        # Tags
        tag_elems = element.select(".tag, .label, .key-word")
        tags = [t.get_text(strip=True) for t in tag_elems]

        # Synopsis
        synopsis_elem = element.select_one(".intro, .desc, .abstract, .book-desc")
        synopsis = synopsis_elem.get_text(strip=True)[:500] if synopsis_elem else ""

        # Word count and status from text
        info_text = element.get_text()
        word_count = self._extract_number(info_text, r"(\d+[\.\d]*)\s*万字")
        status = "completed" if "完结" in info_text else "ongoing"

        return ScrapedBook(
            source="qidian",
            book_id=book_id,
            title=title,
            author=author,
            genre=genre,
            tags=tags,
            word_count=int(word_count * 10000) if word_count else 0,
            chapter_count=0,  # Usually not on list pages
            status=status,
            read_count=0,
            rating=0.0,
            synopsis=synopsis,
            url=f"https://www.qidian.com/book/{book_id}/" if book_id else href,
        )

    # ── Parsing ──────────────────────────────────────────

    def _parse_book(self, raw_data: dict) -> ScrapedBook:
        """Parse raw JSON data (if Qidian ever provides an API)."""
        return ScrapedBook(
            source="qidian",
            book_id=str(raw_data.get("book_id", raw_data.get("id", ""))),
            title=raw_data.get("title", raw_data.get("book_name", "")),
            author=raw_data.get("author", raw_data.get("author_name", "未知")),
            genre=raw_data.get("category", ""),
            tags=raw_data.get("tags", []),
            word_count=int(raw_data.get("word_count", 0)),
            chapter_count=int(raw_data.get("chapter_count", 0)),
            status=raw_data.get("status", ""),
            read_count=int(raw_data.get("read_count", 0)),
            rating=float(raw_data.get("rating", 0)),
            synopsis=raw_data.get("description", "")[:500],
        )

    @staticmethod
    def _extract_number(text: str, pattern: str) -> float:
        """Extract a number from text using regex."""
        match = re.search(pattern, text)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                pass
        return 0.0
