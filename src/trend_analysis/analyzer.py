"""Trend Analyzer — orchestrates the full trend analysis pipeline.

Coordinates:
1. Data collection from scrapers (Fanqie + Qidian)
2. Tag extraction and normalization
3. Genre classification and ranking
4. AI-assisted trope detection (Claude Haiku)
5. Trend report generation
6. Integration with Novel Planner for genre selection
"""

import json
import logging
from datetime import datetime
from typing import Optional

from src.core.models import TrendingElement
from src.data_collection.base import ScrapedBook
from src.data_collection.fanqie_scraper import FanqieScraper
from src.data_collection.qidian_scraper import QidianScraper
from src.data_collection.rate_limiter import RateLimiter
from src.llm.client import LLMClient, LLMResponse
from src.llm.prompt_manager import PromptManager
from src.storage.repositories.trend_repo import TrendRepository
from src.trend_analysis.genre_classifier import GenreClassifier
from src.trend_analysis.tag_extractor import TagExtractor

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """Main trend analysis orchestrator.

    Usage:
        analyzer = TrendAnalyzer(llm_client, prompt_manager, trend_repo)
        report = await analyzer.run_full_analysis()
        # Or use individual steps
        books = await analyzer.collect_data()
        stats = analyzer.analyze(books)
        recommendation = analyzer.recommend()
    """

    def __init__(
        self,
        llm_client: LLMClient,
        prompt_manager: PromptManager,
        trend_repo: TrendRepository,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self.llm = llm_client
        self.prompts = prompt_manager
        self.trend_repo = trend_repo
        self.rate_limiter = rate_limiter or RateLimiter()

        # Sub-analyzers
        self.tag_extractor = TagExtractor()
        self.genre_classifier = GenreClassifier()

        # Scrapers (lazy init)
        self._fanqie: Optional[FanqieScraper] = None
        self._qidian: Optional[QidianScraper] = None

    @property
    def fanqie(self) -> FanqieScraper:
        if self._fanqie is None:
            self._fanqie = FanqieScraper(rate_limiter=self.rate_limiter)
        return self._fanqie

    @property
    def qidian(self) -> QidianScraper:
        if self._qidian is None:
            self._qidian = QidianScraper(rate_limiter=self.rate_limiter)
        return self._qidian

    # ── Main Pipeline ────────────────────────────────────

    async def run_full_analysis(self) -> dict:
        """Run the complete trend analysis pipeline.

        1. Collect data from all platforms
        2. Extract and normalize tags
        3. Classify genre popularity
        4. Save to database
        5. Generate recommendation

        Returns:
            Complete trend report dict.
        """
        logger.info("=" * 50)
        logger.info("Starting full trend analysis pipeline")
        logger.info("=" * 50)

        # Step 1: Collect data
        books = await self.collect_data()

        if not books:
            logger.warning("No books collected — using cached/default data")
            # Try loading from database
            existing = self.trend_repo.get_recent(hours=168)  # Last 7 days
            if existing:
                return self._build_report_from_db(existing)

            return self._get_default_recommendation()

        # Step 2: Analyze
        analysis = self.analyze(books)

        # Step 3: AI-assisted trope detection
        try:
            ai_insights = await self._ai_analyze_tropes(books[:30])
            analysis["ai_insights"] = ai_insights
        except Exception as e:
            logger.warning("AI trope analysis skipped: %s", e)
            analysis["ai_insights"] = {}

        # Step 4: Save trending elements to DB
        self._save_to_db(analysis)

        # Step 5: Build recommendation
        recommendation = self.recommend()
        analysis["recommendation"] = recommendation

        logger.info("Trend analysis complete: %d books, %d tags, recommended=%s",
                     len(books), analysis["tag_stats"]["total_unique_tags"],
                     recommendation.get("genre", "N/A"))

        return analysis

    async def collect_data(self) -> list[ScrapedBook]:
        """Collect book data from all configured platforms."""
        all_books = []

        # Collect from Fanqie
        try:
            logger.info("Collecting from Fanqie...")
            result = await self.fanqie.scrape_ranking("hotsales", limit=50)
            if result.books:
                all_books.extend(result.books)
                logger.info("Fanqie: %d books", len(result.books))
            if result.error:
                logger.warning("Fanqie errors: %s", result.error)
        except Exception as e:
            logger.error("Fanqie collection failed: %s", e)

        # Collect from Qidian
        try:
            logger.info("Collecting from Qidian...")
            result = await self.qidian.scrape_ranking("hotsales", limit=50)
            if result.books:
                all_books.extend(result.books)
                logger.info("Qidian: %d books", len(result.books))
            if result.error:
                logger.warning("Qidian errors: %s", result.error)
        except Exception as e:
            logger.error("Qidian collection failed: %s", e)

        # If scraping failed, use fallback data from config
        if not all_books:
            logger.warning("No books scraped — using config-based trending data")
            all_books = self._generate_fallback_books()

        return all_books

    def analyze(self, books: list[ScrapedBook]) -> dict:
        """Analyze collected books for trends.

        Args:
            books: Collected ScrapedBook objects.

        Returns:
            Analysis results dict.
        """
        # Reset accumulators for fresh analysis
        self.tag_extractor.reset()
        self.genre_classifier.reset()

        # Process through tag extractor
        tag_stats = self.tag_extractor.process_books(books)

        # Process through genre classifier
        self.genre_classifier.process_books(books)
        genre_stats = self.genre_classifier.get_statistics()

        return {
            "total_books": len(books),
            "analysis_time": datetime.utcnow().isoformat(),
            "tag_stats": tag_stats,
            "genre_stats": genre_stats,
        }

    def recommend(self) -> dict:
        """Get AI-assisted genre recommendation for new novels.

        Combines statistical analysis with config-based defaults.
        """
        genre_rec = self.genre_classifier.get_recommended_genre()

        # Also check config for 2025 trending tags
        try:
            from src.config import AppConfig
            config = AppConfig()
            trending_tags = config.trending_tags_2025
            genre_rec["trending_tags_2025"] = trending_tags[:10]
        except Exception:
            genre_rec["trending_tags_2025"] = []

        return genre_rec

    # ── AI-Assisted Analysis ─────────────────────────────

    async def _ai_analyze_tropes(self, books: list[ScrapedBook]) -> dict:
        """Use Claude Haiku to detect emerging tropes from book synopses.

        Cost-optimized: Only sends top 30 books, uses Haiku.
        """
        # Prepare ranking data for the prompt
        ranking_lines = []
        for book in books[:30]:
            tags_str = ", ".join(book.tags[:5]) if book.tags else "无"
            ranking_lines.append(
                f"- [{book.genre}] {book.title} | 标签: {tags_str} | 简介: {book.synopsis[:100]}"
            )
        ranking_data = "\n".join(ranking_lines)

        try:
            system_prompt = self.prompts.render_system("trend_analysis")
            user_prompt = self.prompts.render_user(
                "trend_analysis",
                source=f"番茄小说+起点中文网 (共{len(books)}本)",
                ranking_data=ranking_data,
            )

            response = await self.llm.generate(
                system_prompt=system_prompt,
                user_message=user_prompt,
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                temperature=0.4,
                enable_thinking=False,
                enable_caching=False,
            )

            from src.utils.text_utils import safe_parse_json
            return safe_parse_json(response.text)
        except Exception as e:
            logger.warning("AI trope analysis failed: %s", e)
            return {}

    def _parse_ai_response(self, text: str) -> dict:
        """Parse JSON from AI trope analysis response."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {"raw_response": text[:1000]}

    # ── Persistence ──────────────────────────────────────

    def _save_to_db(self, analysis: dict) -> None:
        """Save trending elements to the database."""
        elements = []

        tag_stats = analysis.get("tag_stats", {})
        for tag_data in tag_stats.get("top_tags", []):
            elements.append(TrendingElement(
                source="fanqie+qidian",
                category="tag",
                name=tag_data["name"],
                frequency=tag_data["frequency"],
                co_occurring=tag_data.get("co_occurring", []),
                collected_at=datetime.utcnow(),
            ))

        genre_stats = analysis.get("genre_stats", {})
        for genre_data in genre_stats.get("ranking", []):
            elements.append(TrendingElement(
                source="fanqie+qidian",
                category="genre",
                name=genre_data["genre"],
                frequency=genre_data["count"],
                growth_rate=1.3 if genre_data.get("trend") == "rising" else 1.0,
                collected_at=datetime.utcnow(),
            ))

        if elements:
            self.trend_repo.save_batch(elements)
            logger.info("Saved %d trending elements to DB", len(elements))

    def _build_report_from_db(self, elements: list[TrendingElement]) -> dict:
        """Build a trend report from cached database data."""
        tags = [e for e in elements if e.category == "tag"]
        genres = [e for e in elements if e.category == "genre"]

        return {
            "total_books": 0,
            "analysis_time": datetime.utcnow().isoformat(),
            "source": "database_cache",
            "tag_stats": {
                "total_unique_tags": len(tags),
                "top_tags": [{"name": t.name, "frequency": t.frequency} for t in tags[:20]],
            },
            "genre_stats": {
                "total_books_analyzed": sum(g.frequency for g in genres),
                "ranking": [
                    {"genre": g.name, "count": g.frequency,
                     "trend": "rising" if g.growth_rate > 1.0 else "stable"}
                    for g in genres
                ],
            },
            "recommendation": self.recommend(),
        }

    def _get_default_recommendation(self) -> dict:
        """Get default recommendation when no data is available."""
        from src.config import AppConfig
        config = AppConfig()

        return {
            "total_books": 0,
            "source": "config_defaults",
            "recommendation": {
                "genre": "玄幻",
                "reason": "使用默认配置（无爬取数据）",
                "hot_elements": config.trending_tags_2025[:5],
                "confidence": 0.3,
            },
        }

    def _generate_fallback_books(self) -> list[ScrapedBook]:
        """Generate synthetic fallback books from config when scraping fails.

        This ensures the trend analysis pipeline doesn't break when
        websites are unreachable.
        """
        from src.config import AppConfig
        config = AppConfig()

        genres = list(config.genres.keys())
        trending_tags = config.trending_tags_2025

        books = []
        for i, genre in enumerate(genres[:5]):
            # Create 5 synthetic books per genre with trending tags
            for j in range(5):
                # Cycle through trending tags
                tag_start = (i * 5 + j) % max(1, len(trending_tags))
                tags = trending_tags[tag_start:tag_start + 3] if trending_tags else ["热门"]

                books.append(ScrapedBook(
                    source="fallback",
                    book_id=f"fallback_{i}_{j}",
                    title=f"《{genre}热门作品{j+1}》",
                    author="人气作者",
                    genre=genre,
                    tags=tags,
                    word_count=500000 + j * 100000,
                    chapter_count=200 + j * 50,
                    status="ongoing",
                    read_count=100000 + j * 50000,
                    rating=8.5 + j * 0.2,
                    synopsis=f"一部精彩的{genre}小说，融合{', '.join(tags)}等热门元素。",
                ))

        logger.info("Generated %d fallback books from config", len(books))
        return books

    async def close(self) -> None:
        """Clean up resources."""
        if self._fanqie:
            await self._fanqie.close()
        if self._qidian:
            await self._qidian.close()
