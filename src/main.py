"""Main entry point for the Novel Writer Agent.

CLI commands:
  python -m src.main status          — Show system status
  python -m src.main test            — Test API connection
  python -m src.main init-db         — Re-initialize database
  python -m src.main create [genre]  — Create a new novel
  python -m src.main generate [id]   — Generate next chapter for a novel
  python -m src.main list            — List all novels
  python -m src.main compile <id>    — Compile all chapters into single TXT
  python -m src.main start           — Start scheduler (daemon mode)
  python -m src.main stop            — Stop scheduler
  python -m src.main jobs            — List scheduled jobs
"""

import asyncio
import logging
import signal
import sys

from src.config import AppConfig
from src.generation.character_designer import CharacterDesigner
from src.generation.chapter_writer import ChapterWriter
from src.generation.context_manager import ContextManager
from src.generation.planner import NovelPlanner
from src.generation.plot_outliner import PlotOutliner
from src.generation.quality_checker import QualityChecker
from src.generation.story_bible import StoryBibleManager
from src.generation.world_builder import WorldBuilder
from src.llm.client import LLMClient
from src.llm.cost_tracker import CostTracker
from src.llm.prompt_manager import PromptManager
from src.publishing.local_publisher import LocalPublisher
from src.scheduler.jobs import (cost_report, generate_evening_chapter,
                                 generate_morning_chapter, health_check, init_jobs,
                                 refresh_trends)
from src.scheduler.scheduler_service import SchedulerService
from src.storage.database import Database
from src.storage.file_store import FileStore
from src.storage.repositories.chapter_repo import ChapterRepository
from src.storage.repositories.novel_repo import NovelRepository
from src.storage.repositories.trend_repo import TrendRepository
from src.trend_analysis.analyzer import TrendAnalyzer
from src.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


class NovelWriterApp:
    """Main application class wiring all components together."""

    def __init__(self):
        # Load configuration
        self.config = AppConfig()

        # Setup logging
        setup_logging(log_dir=self.config.log_dir)

        # Initialize database
        self.db = Database(db_url=self.config.db_url)
        self.db.initialize()

        # Initialize cost tracker
        monthly_budget = self.config.budget.get("monthly_limit_usd", 25.00)
        alert_threshold = self.config.budget.get("alert_threshold", 0.8)
        self.cost_tracker = CostTracker(
            monthly_budget_usd=monthly_budget,
            alert_threshold=alert_threshold,
        )

        # Initialize LLM client
        self.llm_client = LLMClient(cost_tracker=self.cost_tracker)

        # Initialize prompt manager
        self.prompt_manager = PromptManager()

        # Initialize file store
        self.file_store = FileStore(output_dir=self.config.output_dir)

        # Initialize repositories
        session = self.db.create_session()
        self.novel_repo = NovelRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.trend_repo = TrendRepository(session)

        # Initialize generation components
        self.world_builder = WorldBuilder(self.llm_client, self.prompt_manager)
        self.character_designer = CharacterDesigner(self.llm_client, self.prompt_manager)
        self.plot_outliner = PlotOutliner(self.llm_client, self.prompt_manager)
        self.quality_checker = QualityChecker(self.llm_client)
        self.local_publisher = LocalPublisher(self.file_store)
        self.trend_analyzer = TrendAnalyzer(
            llm_client=self.llm_client,
            prompt_manager=self.prompt_manager,
            trend_repo=self.trend_repo,
        )

        # Planner will be initialized with a bible/context per novel
        self._planner: NovelPlanner | None = None

        # Scheduler
        self.scheduler = SchedulerService(
            db_url=self.config.db_url,
            timezone=self.config.scheduling.get("timezone", "Asia/Shanghai"),
        )

        logger.info("Novel Writer Agent v%s initialized", self.config._settings.get("app", {}).get("version", "0.1.0"))

    def _get_planner(self) -> NovelPlanner:
        """Lazy-initialize the planner with shared components."""
        if self._planner is None:
            self._planner = NovelPlanner(
                llm_client=self.llm_client,
                world_builder=self.world_builder,
                character_designer=self.character_designer,
                plot_outliner=self.plot_outliner,
                chapter_writer=None,  # Set per-novel
                quality_checker=self.quality_checker,
                local_publisher=self.local_publisher,
                novel_repo=self.novel_repo,
                chapter_repo=self.chapter_repo,
            )
        return self._planner

    async def test_connection(self) -> bool:
        """Test the connection to Claude API."""
        logger.info("Testing Claude API connection...")
        try:
            response = await self.llm_client.generate(
                system_prompt="你是一个助手。",
                user_message="回复'连接成功'",
                model="claude-haiku-4-5-20251001",
                max_tokens=50,
                enable_thinking=False,
                enable_caching=False,
            )
            print(f"  API test: {response.text.strip()}")
            print(f"  Cost: ${response.cost_usd:.6f} | Latency: {response.latency_ms}ms")
            logger.info("API test successful")
            return True
        except Exception as e:
            logger.error("API test failed: %s", e)
            print(f"  API test FAILED: {e}")
            return False

    async def create_novel(
        self,
        genre: str | None = None,
        elements: list[str] | None = None,
    ):
        """Create a new novel from scratch."""
        planner = self._get_planner()

        print("\n" + "=" * 60)
        print("  Creating New Novel")
        print("=" * 60)

        if genre is None:
            # Use trending tags as default
            genre = "玄幻"
            print(f"  Genre: {genre} (auto-selected)")
        else:
            print(f"  Genre: {genre}")

        if elements is None:
            elements = self.config.trending_tags_2025[:5]
            print(f"  Elements: {', '.join(elements)}")
        else:
            print(f"  Elements: {', '.join(elements)}")

        print("-" * 60)

        try:
            novel = await planner.create_novel(
                genre=genre,
                trending_elements=elements,
            )

            print("-" * 60)
            print(f"  Novel created: {novel.title}")
            print(f"  ID: {novel.id}")
            print(f"  Genre: {novel.genre}")
            print(f"  Chapters planned: {novel.target_chapters}")
            print(f"  Output: {self.config.output_dir / novel.title}")
            print("=" * 60 + "\n")

            return novel
        except Exception as e:
            logger.exception("Failed to create novel")
            print(f"\n  ERROR: {e}\n")
            raise

    async def generate_chapter(self, novel_id: int | None = None):
        """Generate the next chapter for a novel. Auto-creates a novel if none exists."""
        planner = self._get_planner()

        # Find the active novel
        if novel_id is None:
            novel = self.novel_repo.get_active()
            if novel is None:
                novels = self.novel_repo.list_all()
                if novels:
                    novel = novels[0]
                    print(f"Using latest novel: [{novel.id}] {novel.title}")
                else:
                    # Auto-create a novel if none exists
                    print("No novels found. Auto-creating one first...\n")
                    novel = await self.create_novel()
                    if novel is None:
                        return
        else:
            novel = self.novel_repo.get(novel_id)
            if novel is None:
                print(f"Novel {novel_id} not found")
                return

        next_ch = novel.total_chapters + 1
        print(f"\n  Generating Chapter {next_ch} for '{novel.title}'...")

        try:
            chapter, content = await planner.generate_next_chapter(novel)

            # Show preview
            preview = content[:200].replace("\n", " ")
            print(f"  Title: {chapter.title}")
            print(f"  Words: {chapter.word_count}")
            print(f"  Quality: {chapter.quality_score:.2f}")
            print(f"  Preview: {preview}...")
            print(f"  File: {chapter.content_path}")

            # Cost summary
            cost = self.cost_tracker.get_summary()
            print(f"\n  Session cost: ${cost['total_cost_usd']:.4f} | "
                  f"Budget: ${cost['remaining_budget_usd']:.2f} remaining")

            return chapter
        except Exception as e:
            logger.exception("Failed to generate chapter")
            print(f"\n  ERROR: {e}\n")
            raise

    def show_status(self) -> None:
        """Display current system status."""
        print("\n" + "=" * 60)
        print("  Novel Writer Agent — System Status")
        print("=" * 60)
        print(f"  Config:    F:/novel-writer-agent/config/settings.yaml")
        print(f"  Database:  {self.config.db_url}")
        print(f"  Output:    {self.config.output_dir}")
        print(f"  Model:     {self.config.default_model}")
        print("-" * 60)

        # List novels from DB
        novels = self.novel_repo.list_all()
        if novels:
            print(f"  Novels in database ({len(novels)}):")
            for n in novels:
                print(f"    [{n.id}] {n.title} | {n.genre} | "
                      f"Ch.{n.total_chapters}/{n.target_chapters} | {n.status}")
        else:
            print("  No novels in database.")

        # List output files
        output_novels = self.file_store.list_novels()
        if output_novels:
            print(f"\n  Output directories ({len(output_novels)}):")
            for title in output_novels:
                info = self.local_publisher.get_novel_info(title)
                print(f"    - {title} ({info['chapter_count']} chapters)")

        # Cost summary
        cost = self.cost_tracker.get_summary()
        print("-" * 60)
        print(f"  API calls:       {cost['total_calls']}")
        print(f"  Total cost:      ${cost['total_cost_usd']:.4f}")
        print(f"  Monthly budget:  ${cost['monthly_budget_usd']:.2f}")
        print(f"  Remaining:       ${cost['remaining_budget_usd']:.4f}")
        if cost["cache_hit_rate"] > 0:
            print(f"  Cache hit rate:  {cost['cache_hit_rate']:.1%}")
        print("=" * 60 + "\n")

    def compile_novel(self, novel_id: int) -> None:
        """Compile all chapters into a single TXT file."""
        novel = self.novel_repo.get(novel_id)
        if novel is None:
            print(f"Novel {novel_id} not found")
            return

        chapters = self.chapter_repo.list_by_novel(novel_id)
        if not chapters:
            print(f"No chapters for novel {novel_id}")
            return

        from pathlib import Path as _Path
        chapter_data = []
        for ch in chapters:
            if ch.content_path and _Path(ch.content_path).exists():
                with open(ch.content_path, "r", encoding="utf-8") as f:
                    content = f.read()
                chapter_data.append({
                    "number": ch.chapter_number,
                    "title": ch.title,
                    "content": content,
                })

        if chapter_data:
            path = self.local_publisher.compile_novel_txt(novel.title, chapter_data)
            print(f"Compiled {len(chapter_data)} chapters to: {path}")

    def compile_novel_epub(self, novel_id: int) -> None:
        """Compile all chapters into an EPUB file."""
        novel = self.novel_repo.get(novel_id)
        if novel is None:
            print(f"Novel {novel_id} not found")
            return

        chapters = self.chapter_repo.list_by_novel(novel_id)
        if not chapters:
            print(f"No chapters for novel {novel_id}")
            return

        from pathlib import Path as _Path
        chapter_data = []
        for ch in chapters:
            if ch.content_path and _Path(ch.content_path).exists():
                with open(ch.content_path, "r", encoding="utf-8") as f:
                    content = f.read()
                chapter_data.append({
                    "number": ch.chapter_number,
                    "title": ch.title,
                    "content": content,
                })

        if chapter_data:
            path = self.local_publisher.compile_novel_epub(
                novel_title=novel.title,
                author="AI Novel Writer",
                chapters=chapter_data,
                genre=novel.genre,
                synopsis=novel.synopsis or "",
            )
            print(f"EPUB compiled: {path} ({len(chapter_data)} chapters)")

    # ── Scheduler ───────────────────────────────────────

    def start_scheduler(self) -> None:
        """Start the scheduler and register all jobs."""
        print("\n" + "=" * 60)
        print("  Starting Scheduler")
        print("=" * 60)

        # Initialize job globals
        planner = self._get_planner()
        init_jobs(
            planner=planner,
            cost_tracker=self.cost_tracker,
            novel_repo=self.novel_repo,
            chapter_repo=self.chapter_repo,
            file_store=self.file_store,
            db=self.db,
            trend_analyzer=self.trend_analyzer,
        )

        # Start the scheduler
        self.scheduler.start()

        # Get schedule times from config
        sched = self.config.scheduling
        morning_time = sched.get("morning_chapter", "08:00")
        evening_time = sched.get("evening_chapter", "20:00")
        trend_day = sched.get("trend_refresh", {}).get("day", "sun")
        trend_time = sched.get("trend_refresh", {}).get("time", "03:00")
        cost_time = sched.get("cost_report", "23:00")
        health_interval = sched.get("health_check_interval_minutes", 30)

        # Parse times
        morning_h, morning_m = map(int, morning_time.split(":"))
        evening_h, evening_m = map(int, evening_time.split(":"))
        trend_h, trend_m = map(int, trend_time.split(":"))
        cost_h, cost_m = map(int, cost_time.split(":"))

        # Register daily jobs
        self.scheduler.add_daily_job(
            generate_morning_chapter,
            job_id="morning_chapter",
            hour=morning_h,
            minute=morning_m,
            name="Morning Chapter Generation",
        )
        print(f"  ✓ Morning chapter:  {morning_time} daily")

        self.scheduler.add_daily_job(
            generate_evening_chapter,
            job_id="evening_chapter",
            hour=evening_h,
            minute=evening_m,
            name="Evening Chapter Generation",
        )
        print(f"  ✓ Evening chapter:  {evening_time} daily")

        # Register weekly job
        self.scheduler.add_weekly_job(
            refresh_trends,
            job_id="trend_refresh",
            day_of_week=trend_day,
            hour=trend_h,
            minute=trend_m,
            name="Weekly Trend Refresh",
        )
        print(f"  ✓ Trend refresh:    Every {trend_day} at {trend_time}")

        # Register daily cost report
        self.scheduler.add_daily_job(
            cost_report,
            job_id="cost_report",
            hour=cost_h,
            minute=cost_m,
            name="Daily Cost Report",
        )
        print(f"  ✓ Cost report:      {cost_time} daily")

        # Register health check
        self.scheduler.add_interval_job(
            health_check,
            job_id="health_check",
            minutes=health_interval,
            name="Health Check",
        )
        print(f"  ✓ Health check:     Every {health_interval} minutes")

        print("-" * 60)
        self.scheduler.print_jobs()
        print("  Scheduler is RUNNING. Press Ctrl+C to stop.")
        print("=" * 60 + "\n")

    def stop_scheduler(self) -> None:
        """Stop the scheduler gracefully."""
        print("\nStopping scheduler...")
        self.scheduler.shutdown(wait=False)
        print("Scheduler stopped.")

    def show_jobs(self) -> None:
        """Show all scheduled jobs."""
        if self.scheduler.is_running:
            self.scheduler.print_jobs()
        else:
            print("\n  Scheduler is not running. Start it with: python -m src.main start\n")

    def run_daemon(self) -> None:
        """Run the scheduler as a daemon (blocking)."""
        self.start_scheduler()

        # Setup signal handlers for graceful shutdown
        def _shutdown(signum, frame):
            print("\n\nReceived shutdown signal...")
            self.stop_scheduler()
            sys.exit(0)

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        # Keep the main thread alive
        try:
            print("Agent is running. Press Ctrl+C to stop.\n")
            signal.pause()
        except AttributeError:
            # Windows doesn't have signal.pause()
            import time
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                _shutdown(None, None)


# ═══════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════

async def main():
    """CLI entry point."""
    args = sys.argv[1:]
    command = args[0].lower() if args else ""

    # Web command doesn't need full app init — server does its own
    if command == "web":
        import subprocess
        port = args[1] if len(args) > 1 else "8080"
        print(f"\n  Novel Writer Agent Web UI")
        print(f"  http://127.0.0.1:{port}")
        print(f"  按 Ctrl+C 停止\n")
        subprocess.run([
            sys.executable, "-m", "uvicorn",
            "src.web.server:app",
            "--host", "127.0.0.1",
            "--port", port,
            "--log-level", "warning",
        ])
        return

    # All other commands need the full app
    app = NovelWriterApp()

    if not args:
        app.show_status()
        return

    if command == "test":
        success = await app.test_connection()
        if not success:
            sys.exit(1)

    elif command == "status":
        app.show_status()

    elif command == "init-db":
        app.db.initialize(drop_all=True)
        print("Database re-initialized.")

    elif command == "create":
        genre = args[1] if len(args) > 1 else None
        await app.create_novel(genre=genre)

    elif command == "generate":
        novel_id = int(args[1]) if len(args) > 1 else None
        await app.generate_chapter(novel_id=novel_id)

    elif command == "list":
        app.show_status()

    elif command == "compile":
        if len(args) < 2:
            print("Usage: python -m src.main compile <novel_id> [format]")
            print("  format: txt (default) or epub")
            sys.exit(1)
        novel_id = int(args[1])
        fmt = args[2] if len(args) > 2 else "txt"
        if fmt == "epub":
            app.compile_novel_epub(novel_id)
        else:
            app.compile_novel(novel_id)

    elif command == "start":
        app.run_daemon()

    elif command == "stop":
        app.stop_scheduler()

    elif command == "jobs":
        app.show_jobs()

    else:
        print(f"Unknown command: {command}")
        print("Available commands:")
        print("  test              — Test API connection")
        print("  status | list     — Show system status and novels")
        print("  init-db           — Re-initialize database (DESTRUCTIVE)")
        print("  create [genre]    — Create a new novel")
        print("  generate [id]     — Generate next chapter")
        print("  compile <id> [fmt]— Compile chapters to TXT or EPUB")
        print("  web [port]        — Start Web UI (default port 8080)")
        print("  start             — Start scheduler (daemon mode)")
        print("  stop              — Stop scheduler")
        print("  jobs              — List scheduled jobs")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
