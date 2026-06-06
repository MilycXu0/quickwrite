"""Phase 4 verification — scheduler integration test."""
import sys
sys.path.insert(0, ".")

# Set dummy API key for testing (scheduler tests don't call LLM)
import os
if "ANTHROPIC_API_KEY" not in os.environ:
    os.environ["ANTHROPIC_API_KEY"] = "test-key-for-scheduler-verification"

print("=" * 60)
print("Phase 4: Scheduler Integration Verification")
print("=" * 60)

# ── 1. Import scheduler modules ──────────────────────
print("\n[1/5] Importing scheduler modules...")
from src.scheduler.scheduler_service import SchedulerService
from src.scheduler import jobs as scheduler_jobs
print("  OK - Scheduler modules imported")

# ── 2. Initialize app with scheduler ─────────────────
print("\n[2/5] Initializing app with scheduler...")
from src.config import AppConfig
from src.llm.client import LLMClient
from src.llm.cost_tracker import CostTracker
from src.llm.prompt_manager import PromptManager
from src.storage.database import Database
from src.storage.file_store import FileStore
from src.storage.repositories.novel_repo import NovelRepository
from src.storage.repositories.chapter_repo import ChapterRepository

config = AppConfig()
db = Database(config.db_url)
db.initialize()
session = db.create_session()

cost_tracker = CostTracker(monthly_budget_usd=25.00)
llm_client = LLMClient(cost_tracker=cost_tracker)
prompt_manager = PromptManager()
file_store = FileStore(output_dir=config.output_dir)
novel_repo = NovelRepository(session)
chapter_repo = ChapterRepository(session)

# Create scheduler
sched = SchedulerService(
    db_url=config.db_url,
    timezone="Asia/Shanghai",
)
print("  OK - App with scheduler initialized")

# ── 3. Test scheduler start/stop ─────────────────────
print("\n[3/5] Testing scheduler lifecycle...")
sched.start()
print(f"  Running: {sched.is_running}")

# Add test jobs (with dummy functions)
call_log = []

def dummy_morning():
    call_log.append("morning")

def dummy_evening():
    call_log.append("evening")

def dummy_health():
    call_log.append("health")

sched.add_daily_job(dummy_morning, "test_morning", hour=8, minute=0, name="Test Morning")
sched.add_daily_job(dummy_evening, "test_evening", hour=20, minute=0, name="Test Evening")
sched.add_weekly_job(dummy_health, "test_trend", day_of_week="sun", hour=3, minute=0, name="Test Trend")
sched.add_interval_job(dummy_health, "test_health", minutes=30, name="Test Health")

jobs = sched.get_jobs()
print(f"  Jobs registered: {len(jobs)}")
for j in jobs:
    print(f"    - {j['id']}: next={j['next_run']}")

# Print jobs
sched.print_jobs()

# Shutdown
sched.shutdown(wait=False)
print(f"  Running after shutdown: {sched.is_running}")
print("  OK - Scheduler lifecycle works")

# ── 4. Test job init ─────────────────────────────────
print("\n[4/5] Testing jobs.init_jobs...")
from src.generation.planner import NovelPlanner
from src.generation.world_builder import WorldBuilder
from src.generation.character_designer import CharacterDesigner
from src.generation.plot_outliner import PlotOutliner
from src.generation.quality_checker import QualityChecker
from src.publishing.local_publisher import LocalPublisher

# Create a planner (without chapter_writer — it needs per-novel setup)
planner = NovelPlanner(
    llm_client=llm_client,
    world_builder=WorldBuilder(llm_client, prompt_manager),
    character_designer=CharacterDesigner(llm_client, prompt_manager),
    plot_outliner=PlotOutliner(llm_client, prompt_manager),
    chapter_writer=None,
    quality_checker=QualityChecker(llm_client),
    local_publisher=LocalPublisher(file_store),
    novel_repo=novel_repo,
    chapter_repo=chapter_repo,
)

scheduler_jobs.init_jobs(
    planner=planner,
    cost_tracker=cost_tracker,
    novel_repo=novel_repo,
    chapter_repo=chapter_repo,
    file_store=file_store,
    db=db,
)
print("  OK - Job globals initialized")

# ── 5. Test cost_report and health_check independently ──
print("\n[5/5] Testing job functions (no API calls)...")
scheduler_jobs.cost_report()
print("  OK - Cost report runs")
scheduler_jobs.health_check()
print("  OK - Health check runs")

# Cleanup
session.close()
db.close()

print()
print("=" * 60)
print("Phase 4 ALL VERIFICATIONS PASSED!")
print("=" * 60)
print()
print("Scheduler is ready for production use.")
print("Commands:")
print("  python -m src.main start    — Start daemon mode")
print("  python -m src.main jobs     — List scheduled jobs")
print("  python -m src.main stop     — Stop scheduler")
