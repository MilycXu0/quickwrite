"""Phase 1 verification script — test all modules work end-to-end."""
import sys
sys.path.insert(0, ".")

# ── Test core models ──────────────────────────────
from src.core.models import (Base, Chapter, Character, GenerationLog, Novel, PlotPoint,
                              TrendingElement)
from src.core.models import ChapterOutline, Genre, NovelStatus, StoryBible

# ── Test config ───────────────────────────────────
from src.config import AppConfig
config = AppConfig()
print(f"Config loaded: model={config.default_model}")
print(f"Genres: {list(config.genres.keys())[:3]}...")
print(f"DB URL: {config.db_url}")

# ── Test LLM layer ────────────────────────────────
from src.llm.prompt_manager import PromptManager
pm = PromptManager()
world_template = pm.load("world_building")
sys_len = len(world_template.get("system", ""))
print(f"Prompt loaded: world_building system={sys_len} chars")

from src.llm.cost_tracker import CostTracker
ct = CostTracker(monthly_budget_usd=25.00)
ct.record("test", "claude-haiku-4-5", 100, 50, 0, 0, 0.0001, 500)
print(f"Cost tracker: ${ct.get_summary()['total_cost_usd']}")

# ── Test utilities ────────────────────────────────
from src.utils.text_utils import count_chinese_chars, count_words_cn, sanitize_filename
test_text = "这是一个测试，包含中文和English混合。"
print(f"Text utils: chinese_chars={count_chinese_chars(test_text)}, words={count_words_cn(test_text)}")

from src.utils.retry import async_retry, sync_retry
print("Retry decorators imported OK")

# ── Test storage ──────────────────────────────────
from src.storage.database import Database
db = Database(config.db_url)
db.initialize()
print("Database initialized OK")

from src.storage.file_store import FileStore
fs = FileStore(output_dir="F:/novel-writer-agent/output")
print(f"File store: output_dir={fs.output_dir}")

# ── Test repositories ─────────────────────────────
from src.storage.repositories.novel_repo import NovelRepository
from src.storage.repositories.chapter_repo import ChapterRepository
from src.storage.repositories.trend_repo import TrendRepository

session = db.create_session()

# Create and delete a test novel
novel = Novel(title="测试小说", genre="玄幻", subgenre="东方玄幻")
session.add(novel)
session.commit()
print(f"Test novel created: id={novel.id}")

repo = NovelRepository(session)
novels = repo.list_all()
print(f"Novels in DB: {len(novels)}")

session.delete(novel)
session.commit()
session.close()
db.close()

print()
print("=" * 50)
print("Phase 1 ALL VERIFICATIONS PASSED!")
print("=" * 50)
