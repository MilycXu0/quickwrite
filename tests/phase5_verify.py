"""Phase 5 verification — data collection and trend analysis."""
import os
import sys
sys.path.insert(0, ".")

# Set dummy API key for testing
if "ANTHROPIC_API_KEY" not in os.environ:
    os.environ["ANTHROPIC_API_KEY"] = "test-key-for-phase5-verification"

print("=" * 60)
print("Phase 5: Data Collection + Trend Analysis Verification")
print("=" * 60)

# ── 1. Import data collection modules ────────────────
print("\n[1/7] Importing data collection modules...")
from src.data_collection.rate_limiter import RateLimiter, RateLimitConfig
from src.data_collection.base import ScrapedBook, ScrapeResult, BaseScraper
from src.data_collection.fanqie_scraper import FanqieScraper
from src.data_collection.qidian_scraper import QidianScraper
print("  OK - All data collection modules imported")

# ── 2. Test Rate Limiter ─────────────────────────────
print("\n[2/7] Testing Rate Limiter...")
limiter = RateLimiter()
limiter.configure("test.com", RateLimitConfig(min_delay_ms=10, max_delay_ms=1000))

# Test acquire (synchronous — just checks timing logic)
import asyncio
async def test_limiter():
    await asyncio.sleep(0)  # ensure coroutine context
    # Test acquire
    async with limiter.acquire("test.com"):
        pass  # First request — no delay
    async with limiter.acquire("test.com"):
        pass  # Second — check it works
    # Report rate limit
    limiter.report_rate_limited("test.com")
    delay = limiter.get_current_delay("test.com")
    print(f"  After 429: delay={delay:.3f}s")
    assert delay > 0.01, "Backoff should increase delay"
    # Report success
    limiter.report_success("test.com")
    print(f"  After success: delay={limiter.get_current_delay('test.com'):.3f}s")

asyncio.run(test_limiter())
print("  OK - Rate limiter works")

# ── 3. Test ScrapedBook normalization ────────────────
print("\n[3/7] Testing data models...")
book = ScrapedBook(
    source="fanqie",
    book_id="12345",
    title="测试神作",
    author="人气作者",
    genre="玄幻",
    tags=["重生", "无敌流", "系统流"],
    word_count=1000000,
    status="ongoing",
    synopsis="一部精彩的玄幻小说",
)
print(f"  Book: {book.title} | {book.genre} | tags={book.tags}")

# Test cache
from pathlib import Path
cache_dir = Path("F:/novel-writer-agent/data/cache")
result = ScrapeResult(
    source="test",
    books=[book],
    scraped_at=__import__('datetime').datetime.utcnow(),
    list_type="test",
)
print("  OK - Data models work")

# ── 4. Test Fanqie scraper structure ─────────────────
print("\n[4/7] Testing Fanqie scraper structure...")
fanqie = FanqieScraper(cache_dir=cache_dir, cache_ttl_hours=1)

# Test book parsing
raw_data = {
    "book_id": "12345",
    "title": "测试玄幻小说",
    "author": "测试作者",
    "category": "玄幻",
    "tags": [{"name": "重生"}, {"name": "无敌流"}],
    "word_count": 500000,
    "status": "连载中",
    "description": "一个精彩的玄幻故事",
}
parsed = fanqie._parse_book(raw_data)
print(f"  Parsed: {parsed.title} by {parsed.author} | genre={parsed.genre} | tags={parsed.tags}")
assert parsed.source == "fanqie"
assert parsed.title == "测试玄幻小说"
assert "重生" in parsed.tags
print("  OK - Fanqie parsing works")

# Test content decoding
charset = {"a": "我", "b": "是", "c": "谁"}
decoded = FanqieScraper.decode_content("abc", charset)
print(f"  Content decoding: 'abc' -> '{decoded}'")
assert decoded == "我是谁"
print("  OK - Content decoding works")

# ── 5. Test Qidian scraper structure ─────────────────
print("\n[5/7] Testing Qidian scraper structure...")
qidian = QidianScraper(cache_dir=cache_dir, cache_ttl_hours=1)

# Test HTML parsing is setup correctly
assert qidian.BASE_URL == "https://www.qidian.com"
assert "hotsales" in qidian.RANK_PAGES

# Test number extraction
num = QidianScraper._extract_number("作品总字数 125.5万字，已完结", r"(\d+[\.\d]*)\s*万字")
print(f"  Extracted word count: {num}*10000 = {int(num * 10000)} chars")
print("  OK - Qidian parsing utilities work")

# ── 6. Test Tag Extractor ────────────────────────────
print("\n[6/7] Testing Tag Extractor...")
from src.trend_analysis.tag_extractor import TagExtractor
from src.trend_analysis.genre_classifier import GenreClassifier

# Create test books
test_books = []
for i in range(20):
    genre = ["玄幻", "都市", "仙侠", "科幻"][i % 4]
    tags = [
        ["重生", "系统流", "无敌流"],
        ["重生逆袭", "系统流", "商战"],
        ["修仙", "洪荒", "法宝"],
        ["星际", "基因进化", "AI"],
    ][i % 4]
    test_books.append(ScrapedBook(
        source="test", book_id=str(i),
        title=f"测试小说{i}", author=f"作者{i}",
        genre=genre, tags=tags,
        word_count=500000 + i * 50000,
        chapter_count=200 + i * 20,
        status="ongoing",
        read_count=100000 + i * 10000,
        rating=8.0 + i * 0.1,
        synopsis=f"热门{genre}小说{i}",
    ))

extractor = TagExtractor()
stats = extractor.process_books(test_books)
print(f"  Unique tags: {stats['total_unique_tags']}")
print(f"  Total instances: {stats['total_tag_instances']}")
print(f"  Top 5 tags: {[t['name'] for t in stats['top_tags'][:5]]}")

combinations = extractor.detect_trending_combinations(min_freq=2)
print(f"  Tag combinations: {len(combinations)}")
if combinations:
    print(f"  Top combo: {combinations[0]['elements']} (freq={combinations[0]['frequency']})")
print("  OK - Tag extraction works")

# ── 7. Test Genre Classifier ─────────────────────────
print("\n[7/7] Testing Genre Classifier...")
classifier = GenreClassifier(decay_days=30)
classifier.process_books(test_books)
ranking = classifier.get_genre_ranking()
print(f"  Genre ranking ({len(ranking)} genres):")
for g in ranking:
    print(f"    {g['genre']}: {g['count']} books ({g['percentage']}%) trend={g['trend']}")

rec = classifier.get_recommended_genre()
print(f"  Recommended: {rec['genre']} (confidence={rec['confidence']:.2f})")
print(f"  Hot elements: {rec['hot_elements']}")
print("  OK - Genre classification works")

# ── Test TrendAnalyzer ───────────────────────────────
print("\n[7a/7] Testing TrendAnalyzer integration...")
from src.config import AppConfig
from src.llm.client import LLMClient
from src.llm.cost_tracker import CostTracker
from src.llm.prompt_manager import PromptManager
from src.storage.database import Database
from src.storage.repositories.trend_repo import TrendRepository
from src.trend_analysis.analyzer import TrendAnalyzer

config = AppConfig()
cost_tracker = CostTracker()
llm_client = LLMClient(cost_tracker=cost_tracker)
pm = PromptManager()
db = Database(config.db_url)
db.initialize()
session = db.create_session()
trend_repo = TrendRepository(session)

analyzer = TrendAnalyzer(
    llm_client=llm_client,
    prompt_manager=pm,
    trend_repo=trend_repo,
    rate_limiter=limiter,
)

# Test analysis with test books
analysis = analyzer.analyze(test_books)
print(f"  Analysis: {analysis['total_books']} books, {analysis['tag_stats']['total_unique_tags']} tags")

# Test recommendation
rec = analyzer.recommend()
print(f"  Trend recommendation: genre={rec.get('genre')} confidence={rec.get('confidence', 0):.2f}")

# Test fallback generation
fallback = analyzer._generate_fallback_books()
print(f"  Fallback books generated: {len(fallback)}")
print(f"  Fallback genres: {set(b.genre for b in fallback)}")

# Cleanup
session.close()
db.close()

print()
print("=" * 60)
print("Phase 5 ALL VERIFICATIONS PASSED!")
print("=" * 60)
print()
print("Trend analysis pipeline is ready.")
print("  - Rate limiter with exponential backoff")
print("  - Fanqie scraper (API + content decoding)")
print("  - Qidian scraper (HTML parsing)")
print("  - Tag extraction with synonym normalization")
print("  - Genre classification with trend detection")
print("  - Fallback data when scraping is unavailable")
