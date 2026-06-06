"""Job definitions for the novel writer agent scheduler.

Jobs:
- morning_chapter: Generate and publish the morning chapter at 08:00
- evening_chapter: Generate and publish the evening chapter at 20:00
- trend_refresh: Weekly trend analysis refresh (Sunday 03:00)
- cost_report: Daily cost summary (23:00)
- health_check: System health check every 30 minutes
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from src.config import AppConfig
from src.generation.planner import NovelPlanner
from src.llm.cost_tracker import CostTracker
from src.llm.prompt_manager import PromptManager
from src.storage.database import Database
from src.storage.file_store import FileStore
from src.storage.repositories.chapter_repo import ChapterRepository
from src.storage.repositories.novel_repo import NovelRepository
from src.trend_analysis.analyzer import TrendAnalyzer

logger = logging.getLogger(__name__)

# Global references set during scheduler initialization
_planner: Optional[NovelPlanner] = None
_cost_tracker: Optional[CostTracker] = None
_novel_repo: Optional[NovelRepository] = None
_chapter_repo: Optional[ChapterRepository] = None
_file_store: Optional[FileStore] = None
_db: Optional[Database] = None
_trend_analyzer: Optional[TrendAnalyzer] = None
_learning_engine = None  # WritingAnalytics instance


def init_jobs(
    planner: NovelPlanner,
    cost_tracker: CostTracker,
    novel_repo: NovelRepository,
    chapter_repo: ChapterRepository,
    file_store: FileStore,
    db: Database,
    trend_analyzer: Optional[TrendAnalyzer] = None,
    learning_engine=None,
) -> None:
    """Initialize the global references for job functions."""
    global _planner, _cost_tracker, _novel_repo, _chapter_repo, _file_store, _db, _trend_analyzer, _learning_engine
    _planner = planner
    _cost_tracker = cost_tracker
    _novel_repo = novel_repo
    _chapter_repo = chapter_repo
    _file_store = file_store
    _db = db
    _trend_analyzer = trend_analyzer
    _learning_engine = learning_engine
    logger.info("Job globals initialized (learning=%s)", learning_engine is not None)


# ═══════════════════════════════════════════════════════════
# Job Functions
# ═══════════════════════════════════════════════════════════

async def generate_morning_chapter(novel_id: Optional[int] = None):
    """Generate the morning chapter (08:00 daily)."""
    logger.info("=" * 50)
    logger.info("JOB: Morning Chapter Generation — %s", datetime.now().isoformat())
    logger.info("=" * 50)

    try:
        # Find the active novel
        novel = _get_active_novel(novel_id)
        if novel is None:
            logger.warning("No active novel found for morning chapter generation")
            return

        # Generate chapter
        chapter, content = await _planner.generate_next_chapter(novel)

        logger.info("Morning chapter %d completed: '%s' (%d chars)",
                     chapter.chapter_number, chapter.title, len(content))

        # Log cost
        summary = _cost_tracker.get_summary()
        logger.info("Session cost: $%.4f | Remaining budget: $%.2f",
                     summary["total_cost_usd"], summary["remaining_budget_usd"])

    except Exception as e:
        logger.exception("Morning chapter generation FAILED: %s", e)


async def generate_evening_chapter(novel_id: Optional[int] = None):
    """Generate the evening chapter (20:00 daily)."""
    logger.info("=" * 50)
    logger.info("JOB: Evening Chapter Generation — %s", datetime.now().isoformat())
    logger.info("=" * 50)

    try:
        novel = _get_active_novel(novel_id)
        if novel is None:
            logger.warning("No active novel found for evening chapter generation")
            return

        chapter, content = await _planner.generate_next_chapter(novel)

        logger.info("Evening chapter %d completed: '%s' (%d chars)",
                     chapter.chapter_number, chapter.title, len(content))

        summary = _cost_tracker.get_summary()
        logger.info("Session cost: $%.4f | Remaining budget: $%.2f",
                     summary["total_cost_usd"], summary["remaining_budget_usd"])

    except Exception as e:
        logger.exception("Evening chapter generation FAILED: %s", e)


async def refresh_trends():
    """Weekly trend analysis refresh (Sunday 03:00)."""
    logger.info("=" * 50)
    logger.info("JOB: Weekly Trend Refresh — %s", datetime.now().isoformat())
    logger.info("=" * 50)

    if _trend_analyzer is None:
        logger.warning("Trend analyzer not initialized — using config defaults")
        try:
            config = AppConfig()
            trending_tags = config.trending_tags_2025
            logger.info("Default trending elements: %s", ", ".join(trending_tags[:10]))
        except Exception as e:
            logger.exception("Config fallback FAILED: %s", e)
        return

    try:
        report = await _trend_analyzer.run_full_analysis()

        logger.info("Trend refresh complete:")
        logger.info("  Books analyzed: %d", report.get("total_books", 0))
        logger.info("  Recommended genre: %s", report.get("recommendation", {}).get("genre", "N/A"))
        if "tag_stats" in report:
            top_tags = [t["name"] for t in report["tag_stats"].get("top_tags", [])[:5]]
            logger.info("  Top tags: %s", ", ".join(top_tags))

        # Log genre ranking
        genre_ranking = report.get("genre_stats", {}).get("ranking", [])
        for g in genre_ranking[:5]:
            logger.info("  Genre: %s | count=%d | trend=%s",
                         g["genre"], g["count"], g.get("trend", "stable"))

    except Exception as e:
        logger.exception("Trend refresh FAILED: %s", e)


def cost_report():
    """Daily cost summary (23:00)."""
    logger.info("=" * 50)
    logger.info("JOB: Daily Cost Report — %s", datetime.now().isoformat())
    logger.info("=" * 50)

    try:
        summary = _cost_tracker.get_summary()

        report_lines = [
            f"Daily Cost Report — {datetime.now().strftime('%Y-%m-%d')}",
            f"  API calls today:       {summary['total_calls']}",
            f"  Total cost:            ${summary['total_cost_usd']:.4f}",
            f"  Input tokens:          {summary['total_input_tokens']:,}",
            f"  Output tokens:         {summary['total_output_tokens']:,}",
            f"  Cache read tokens:     {summary['total_cache_read_tokens']:,}",
            f"  Cache hit rate:        {summary['cache_hit_rate']:.1%}",
            f"  Monthly budget:        ${summary['monthly_budget_usd']:.2f}",
            f"  Remaining budget:      ${summary['remaining_budget_usd']:.4f} ({summary['budget_percent']:.1f}% used)",
        ]

        for line in report_lines:
            logger.info(line)

        # Also write to cost log file
        cost_logger = logging.getLogger("src.llm.cost_tracker")
        cost_logger.info("\n".join(report_lines))

        # Alert if budget is running low
        if summary["budget_percent"] > 80:
            logger.warning("⚠️ BUDGET ALERT: %.1f%% of monthly budget consumed!", summary["budget_percent"])

    except Exception as e:
        logger.exception("Cost report FAILED: %s", e)


def health_check():
    """System health check (every 30 minutes)."""
    try:
        # Check database connection
        if _db:
            session = _db.create_session()
            session.execute(text("SELECT 1"))
            session.close()

        # Check output directory
        if _file_store and not _file_store.output_dir.exists():
            logger.error("Output directory missing: %s", _file_store.output_dir)

        # Log minimal stats
        novels = _novel_repo.list_all()
        active_count = sum(1 for n in novels if n.status == "writing")

        logger.debug("Health check OK | novels=%d | active=%d | cost=$%.4f",
                      len(novels), active_count, _cost_tracker.total_cost)

    except Exception as e:
        logger.error("Health check FAILED: %s", e)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

async def weekly_learning():
    """Weekly learning cycle — analyze writing patterns and update knowledge base.

    Runs alongside trend refresh to combine market data with self-analysis.
    """
    logger.info("=" * 50)
    logger.info("JOB: Weekly Learning Cycle — %s", datetime.now().isoformat())
    logger.info("=" * 50)

    if _learning_engine is None:
        logger.warning("Learning engine not initialized — skipping weekly learning")
        return

    try:
        report = await _learning_engine.run_analysis_cycle()

        logger.info("Learning cycle complete:")
        logger.info("  Chapters analyzed: %d", report.total_chapters_analyzed)
        logger.info("  Quality trend:     %s", report.quality_trend)
        logger.info("  Avg quality:       %.2f", report.avg_quality)
        logger.info("  Suggestions:       %d", len(report.improvement_suggestions))
        for s in report.improvement_suggestions[:3]:
            logger.info("    • %s", s)

        if report.best_chapter:
            logger.info("  Best chapter:  #%d (%.2f)", report.best_chapter["chapter_number"], report.best_chapter["quality_score"])
        if report.worst_chapter:
            logger.info("  Worst chapter: #%d (%.2f)", report.worst_chapter["chapter_number"], report.worst_chapter["quality_score"])

    except Exception as e:
        logger.exception("Weekly learning cycle FAILED: %s", e)


def _get_active_novel(novel_id: Optional[int] = None):
    """Get the novel to generate chapters for."""
    if novel_id:
        return _novel_repo.get(novel_id)

    # Find active novel (status == writing)
    novel = _novel_repo.get_active()
    if novel:
        return novel

    # Fall back to most recent novel
    novels = _novel_repo.list_all()
    if novels:
        logger.info("No active novel, using latest: [%d] %s", novels[0].id, novels[0].title)
        return novels[0]

    return None
