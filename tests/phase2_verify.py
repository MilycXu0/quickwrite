"""Phase 2 verification — test all generation modules import and initialize."""
import sys
sys.path.insert(0, ".")

print("=" * 60)
print("Phase 2 Integration Verification")
print("=" * 60)

# ── 1. Import all generation modules ──────────────────
print("\n[1/6] Importing generation modules...")
from src.generation.story_bible import StoryBibleManager
from src.generation.world_builder import WorldBuilder
from src.generation.character_designer import CharacterDesigner
from src.generation.plot_outliner import PlotOutliner
from src.generation.context_manager import ContextManager
from src.generation.chapter_writer import ChapterWriter
from src.generation.quality_checker import QualityChecker
from src.generation.planner import NovelPlanner
print("  OK - All generation modules imported")

# ── 2. Initialize app components ──────────────────────
print("\n[2/6] Initializing app components...")
from src.config import AppConfig
from src.llm.client import LLMClient
from src.llm.prompt_manager import PromptManager
from src.storage.database import Database
from src.storage.file_store import FileStore
from src.storage.repositories.novel_repo import NovelRepository
from src.storage.repositories.chapter_repo import ChapterRepository

config = AppConfig()
db = Database(config.db_url)
db.initialize()
session = db.create_session()
file_store = FileStore(output_dir=config.output_dir)
prompt_manager = PromptManager()

novel_repo = NovelRepository(session)
chapter_repo = ChapterRepository(session)
print("  OK - All components initialized")

# ── 3. Test Story Bible ───────────────────────────────
print("\n[3/6] Testing Story Bible...")
bible = StoryBibleManager(novel_id=1, novel_title="测试小说")

# Initialize world
world_data = {
    "world_name": "苍云大陆",
    "world_type": "东方玄幻",
    "era": "上古纪元",
    "geography": {"description": "一片广袤的修炼大陆"},
    "power_system": {
        "name": "武道体系",
        "levels": [
            {"name": "练气期", "description": "引气入体"},
            {"name": "筑基期", "description": "筑就根基"}
        ]
    },
}
bible.initialize_world(world_data)

# Initialize characters
chars_data = {
    "protagonist": {
        "name": "林风",
        "role": "protagonist",
        "motivation": "成为最强武者",
        "starting_location": "青云镇",
        "starting_power": "练气期",
    },
    "supporting_characters": [
        {"name": "苏灵", "role": "love_interest", "relationship_to_mc": "青梅竹马"}
    ],
    "antagonists": [
        {"name": "黑影老祖", "motivation": "统治大陆", "strength": "元婴期"}
    ],
}
bible.initialize_characters(chars_data)

# Test operations
bible.add_chapter_summary(1, "第一章：主角在青云镇觉醒武魂")
bible.add_plot_thread("main_quest", "寻找传说中的九天神剑", 1)
bible.add_event(1, "林风觉醒九阳武魂")
bible.update_character("林风", power_level="筑基期", current_location="青云宗")

# Verify
assert len(bible.get_character_names()) == 3
assert bible.get_active_plot_threads()[0]["id"] == "main_quest"
assert bible.get_character("林风").power_level == "筑基期"
context = bible.get_full_context()
assert "苍云大陆" in context["world_setting"]
assert "林风" in context["character_states"]
print("  OK - Story Bible operations verified")

# ── 4. Test Context Manager ───────────────────────────
print("\n[4/6] Testing Context Manager...")
# Skip LLM client init if no API key
import os
has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

ctx = ContextManager(
    llm_client=None,  # Not used in assembly
    prompt_manager=prompt_manager,
    story_bible=bible,
)
ctx._recent_chapters = ["第一章测试内容：林风在青云镇觉醒了武魂。"]
ctx._chapter_summaries[1] = "第一章摘要：主角觉醒武魂"

chapter_ctx = ctx.assemble(
    novel_title="测试小说",
    genre="玄幻",
    chapter_number=2,
    chapter_title="初入宗门",
    chapter_outline="1. 林风进入青云宗\n2. 遭遇宗门歧视\n3. 展示九阳武魂实力",
    pov_character="林风",
    characters_appearing="林风, 苏灵, 宗门长老",
    target_words=2000,
)
print(f"  System prompt: {len(chapter_ctx.system_prompt)} chars")
print(f"  User prompt: {len(chapter_ctx.user_prompt)} chars")
print(f"  Estimated tokens: {chapter_ctx.estimated_tokens}")
assert "林风" in chapter_ctx.system_prompt
assert "2" in chapter_ctx.user_prompt and "初入宗门" in chapter_ctx.user_prompt
print("  OK - Context assembly verified")

# ── 5. Test Quality Checker (no API) ──────────────────
print("\n[5/6] Testing Quality Checker...")
from src.utils.text_utils import count_chinese_chars, count_words_cn, sanitize_filename

# Test text utils
test_chapter = """
林风站在青云宗的山门前，望着巍峨的山峰，心中涌起一股豪情。
"这就是青云宗吗？"他喃喃自语道。
"没错，"身边的苏灵微笑着说，"从今天起，我们就是青云宗的弟子了。"
两人并肩走入山门，周围的弟子纷纷投来好奇的目光。
林风握紧拳头，暗自下定决心：一定要在这青云宗闯出一片天地！
"""
wc = count_words_cn(test_chapter)
cc = count_chinese_chars(test_chapter)
print(f"  Test chapter: {wc} words, {cc} chinese chars")
print(f"  Sanitized filename: {sanitize_filename('测试小说:风云录？')}")
print("  OK - Text utilities work")

# Test QualityChecker structure checks (no API needed)
qc = QualityChecker(llm_client=None)
struct_score = qc._check_structure(test_chapter)
dialogue_score = qc._check_dialogue(test_chapter)
rep_score = qc._check_repetition(test_chapter)
print(f"  Structure: {struct_score:.2f}, Dialogue: {dialogue_score:.2f}, Repetition: {rep_score:.2f}")
print("  OK - Quality checks (local) work")

# ── 6. Test Local Publisher ───────────────────────────
print("\n[6/6] Testing Local Publisher...")
from src.publishing.local_publisher import LocalPublisher

publisher = LocalPublisher(file_store)
path = publisher.publish_chapter(
    novel_title="测试小说",
    chapter_number=1,
    chapter_title="武魂觉醒",
    content=test_chapter,
)
print(f"  Published chapter to: {path}")
assert path.exists()
print(f"  File exists: {path.exists()}")
print(f"  File size: {path.stat().st_size} bytes")

# Compile test
chapters = [
    {"number": 1, "title": "武魂觉醒", "content": test_chapter},
]
compiled_path = publisher.compile_novel_txt("测试小说", chapters)
print(f"  Compiled novel to: {compiled_path}")

info = publisher.get_novel_info("测试小说")
print(f"  Novel info: {info['chapter_count']} chapters")

print()
print("=" * 60)
print("Phase 2 ALL VERIFICATIONS PASSED!")
print("=" * 60)

# Cleanup
session.close()
db.close()
