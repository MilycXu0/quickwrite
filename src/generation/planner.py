"""Novel Planner — orchestrates the full novel creation and chapter generation pipeline.

This is the top-level coordinator that:
1. Plans a new novel (genre selection, world-building, character design, plot outlining)
2. Generates individual chapters on demand
3. Manages the full novel lifecycle
"""

import json
import logging
from datetime import datetime
from typing import Optional

from src.core.models import Chapter, ChapterOutline, ChapterStatus, Novel, NovelStatus
from src.generation.character_designer import CharacterDesigner
from src.generation.chapter_writer import ChapterWriter
from src.generation.context_manager import ContextManager
from src.generation.plot_outliner import PlotOutliner
from src.generation.quality_checker import QualityChecker
from src.generation.story_bible import StoryBible, StoryBibleManager
from src.generation.world_builder import WorldBuilder
from src.llm.client import LLMClient
from src.publishing.local_publisher import LocalPublisher
from src.storage.repositories.chapter_repo import ChapterRepository
from src.storage.repositories.novel_repo import NovelRepository

logger = logging.getLogger(__name__)


class NovelPlanner:
    """Orchestrates novel creation from planning through chapter generation.

    Usage:
        planner = NovelPlanner(...)
        novel = await planner.create_novel(genre="玄幻")
        chapter, content = await planner.generate_next_chapter(novel)
    """

    def __init__(
        self,
        llm_client: LLMClient,
        world_builder: WorldBuilder,
        character_designer: CharacterDesigner,
        plot_outliner: PlotOutliner,
        chapter_writer: ChapterWriter,
        quality_checker: QualityChecker,
        local_publisher: LocalPublisher,
        novel_repo: NovelRepository,
        chapter_repo: ChapterRepository,
        style_optimizer=None,
    ):
        self.llm = llm_client
        self.world_builder = world_builder
        self.character_designer = character_designer
        self.plot_outliner = plot_outliner
        self.chapter_writer = chapter_writer
        self.quality_checker = quality_checker
        self.publisher = local_publisher
        self.novel_repo = novel_repo
        self.chapter_repo = chapter_repo
        self.style_optimizer = style_optimizer

        # Active story bibles (novel_id -> StoryBibleManager)
        self._bibles: dict[int, StoryBibleManager] = {}
        # Active context managers (novel_id -> ContextManager)
        self._contexts: dict[int, ContextManager] = {}
        # Cached outlines (novel_id -> list[ChapterOutline])
        self._outlines: dict[int, list[ChapterOutline]] = {}

    # ── Novel Creation ──────────────────────────────────

    async def create_novel(
        self,
        genre: Optional[str] = None,
        trending_elements: Optional[list[str]] = None,
        extra_requirements: str = "",
        trend_analyzer=None,
    ) -> Novel:
        """Create a new novel from scratch.

        This runs the full planning pipeline:
        1. Select genre and trending elements (auto if not specified)
        2. Build world setting
        3. Design characters
        4. Generate initial chapter outlines
        5. Initialize Story Bible and Context Manager

        Args:
            genre: Primary genre. If None, auto-selects from trends or defaults to 玄幻.
            trending_elements: Hot elements to incorporate. Auto-selects if None.
            extra_requirements: Additional creative constraints.
            trend_analyzer: Optional TrendAnalyzer for auto-selection.

        Returns:
            The created Novel ORM object.
        """
        # Auto-select genre and elements if not provided
        if genre is None or trending_elements is None:
            rec = self._get_trend_recommendation(trend_analyzer)
            if genre is None:
                genre = rec.get("genre", "玄幻")
                logger.info("Auto-selected genre: %s (confidence=%.2f)", genre, rec.get("confidence", 0))
            if trending_elements is None:
                trending_elements = rec.get("hot_elements", ["系统流", "重生", "逆袭"])
                logger.info("Auto-selected elements: %s", trending_elements)

        genre = genre or "玄幻"
        trending_elements = trending_elements or ["系统流", "无敌流"]
        trending_str = ", ".join(trending_elements)

        logger.info("=" * 60)
        logger.info("Creating new novel: genre=%s", genre)
        logger.info("Trending elements: %s", trending_str)
        logger.info("=" * 60)

        # Step 1: Build world
        logger.info("Step 1/5: Building world...")
        world = await self.world_builder.build(
            genre=genre,
            trending_elements=trending_elements,
            extra_requirements=extra_requirements,
        )

        # Step 2: Design characters
        logger.info("Step 2/5: Designing characters...")
        world_summary = json.dumps(world.model_dump(), ensure_ascii=False, indent=2)
        characters = await self.character_designer.design(
            genre=genre,
            world_summary=world_summary[:3000],
            trending_elements=trending_elements,
        )

        # Step 3: Create novel record
        logger.info("Step 3/5: Creating novel record...")
        protag = characters.get("protagonist", {})
        novel_title = protag.get("suggested_title", f"《{world.world_name}》")

        novel = Novel(
            title=novel_title,
            genre=genre,
            subgenre=world.world_type or "",
            synopsis=protag.get("background", "")[:500],
            status=NovelStatus.PLANNING.value,
            target_chapters=100,
            total_chapters=0,
            trending_elements={
                "tags": trending_elements,
                "world_type": world.world_type,
                "protagonist_type": protag.get("golden_finger", {}).get("type", ""),
            },
            world_setting=world.model_dump(),
        )
        novel = self.novel_repo.create(novel)

        # Step 4: Initialize Story Bible
        logger.info("Step 4/5: Initializing Story Bible...")
        bible = StoryBibleManager(novel_id=novel.id, novel_title=novel.title)
        bible.initialize_world(world.model_dump())
        bible.initialize_characters(characters)
        self._bibles[novel.id] = bible

        # Save bible
        from src.storage.file_store import FileStore
        from src.llm.prompt_manager import PromptManager
        fs = FileStore()
        fs.save_story_bible(novel.title, bible.to_dict())

        # Step 5: Generate initial outlines
        logger.info("Step 5/5: Generating initial chapter outlines...")
        try:
            outlines = await self.plot_outliner.generate_outlines(
                novel_title=novel.title,
                genre=genre,
                world_summary=world_summary[:1000],
                protagonist_name=protag.get("name", "主角"),
                protagonist_state=protag.get("background", "")[:500],
                active_plots="故事刚开始，暂无进行中的情节线",
                recent_events="故事即将开始",
                start_chapter=1,
                end_chapter=10,
            )
        except ValueError:
            # Retry with even smaller batch on JSON parse failure
            logger.warning("Initial outline gen failed (10 chapters), retrying with 5...")
            outlines = await self.plot_outliner.generate_outlines(
                novel_title=novel.title,
                genre=genre,
                world_summary=world_summary[:1000],
                protagonist_name=protag.get("name", "主角"),
                protagonist_state=protag.get("background", "")[:500],
                active_plots="故事刚开始，暂无进行中的情节线",
                recent_events="故事即将开始",
                start_chapter=1,
                end_chapter=5,
            )
        self._outlines[novel.id] = outlines

        # Save outlines to chapter records (upsert to avoid duplicates)
        for outline in outlines:
            chapter = Chapter(
                novel_id=novel.id,
                chapter_number=outline.chapter_number,
                title=outline.title,
                status=ChapterStatus.DRAFT.value,
                outline=outline.model_dump(),
            )
            self.chapter_repo.upsert(chapter)

        # Mark novel as ready to write
        novel.status = NovelStatus.WRITING.value
        novel.updated_at = datetime.utcnow()
        self.novel_repo.session.commit()

        # Publish metadata
        self.publisher.publish_novel_metadata(novel.title, {
            "title": novel.title,
            "genre": novel.genre,
            "subgenre": novel.subgenre,
            "synopsis": novel.synopsis,
            "trending_elements": novel.trending_elements,
            "target_chapters": novel.target_chapters,
            "created_at": novel.created_at.isoformat() if novel.created_at else "",
            "world_building": world.model_dump(),
            "characters": characters,
        })

        logger.info("=" * 60)
        logger.info("Novel created successfully!")
        logger.info("  Title: %s", novel.title)
        logger.info("  Genre: %s", novel.genre)
        logger.info("  World: %s", world.world_name)
        logger.info("  Characters: %d", len(bible.get_character_names()))
        logger.info("  Outlines ready: %d chapters", len(outlines))
        logger.info("=" * 60)

        return novel

    # ── Chapter Generation ──────────────────────────────

    async def generate_next_chapter(self, novel: Novel) -> tuple[Chapter, str]:
        """Generate the next chapter for an active novel.

        Args:
            novel: The Novel object to continue.

        Returns:
            Tuple of (Chapter, content text).
        """
        # Ensure context manager exists
        if novel.id not in self._contexts:
            self._init_context_manager(novel)

        # Get or extend outlines
        outlines = self._outlines.get(novel.id, [])
        next_chapter_num = novel.total_chapters + 1

        outline = self._find_outline(outlines, next_chapter_num)
        if outline is None:
            # Need more outlines — extend
            logger.info("Extending outlines beyond chapter %d", next_chapter_num - 1)
            bible = self._bibles.get(novel.id)
            world_summary = json.dumps(novel.world_setting or {}, ensure_ascii=False)[:1000]
            protag = bible.get_protagonist()
            protag_name = protag[0] if protag else "主角"
            protag_state = protag[1].model_dump_json() if protag else ""

            new_outlines = await self._generate_outlines_with_retry(
                novel=novel,
                bible=bible,
                world_summary=world_summary,
                protag_name=protag_name,
                protag_state=protag_state[:500],
                next_chapter_num=next_chapter_num,
            )
            outlines.extend(new_outlines)
            self._outlines[novel.id] = outlines

            # Save new outlines to DB (upsert to avoid duplicates)
            for o in new_outlines:
                ch = Chapter(
                    novel_id=novel.id,
                    chapter_number=o.chapter_number,
                    title=o.title,
                    status=ChapterStatus.DRAFT.value,
                    outline=o.model_dump(),
                )
                self.chapter_repo.upsert(ch)

            outline = self._find_outline(outlines, next_chapter_num)

        if outline is None:
            raise RuntimeError(f"Failed to get outline for chapter {next_chapter_num}")

        # Ensure chapter writer is initialized
        writer = self._get_chapter_writer(novel)

        # Generate the chapter
        chapter, content = await writer.write_chapter(
            novel=novel,
            outline=outline,
            special_instructions="",
        )

        return chapter, content

    async def _generate_outlines_with_retry(
        self, novel, bible, world_summary, protag_name, protag_state, next_chapter_num
    ) -> list[ChapterOutline]:
        """Generate outlines with fallback: try 20 chapters, then 10 if truncated."""
        batch_size = 10
        for attempt in range(2):
            try:
                end_ch = next_chapter_num + batch_size - 1
                logger.info(
                    "Generating outlines ch.%d-%d (batch=%d, attempt=%d)",
                    next_chapter_num, end_ch, batch_size, attempt + 1,
                )
                outlines = await self.plot_outliner.generate_outlines(
                    novel_title=novel.title,
                    genre=novel.genre,
                    world_summary=world_summary,
                    protagonist_name=protag_name,
                    protagonist_state=protag_state[:500],
                    active_plots=bible.get_plot_context() if bible else "",
                    recent_events=bible.get_timeline_context(10) if bible else "",
                    start_chapter=next_chapter_num,
                    end_chapter=end_ch,
                )
                if outlines:
                    return outlines
            except Exception as e:
                logger.warning("Outline generation attempt %d failed (batch=%d): %s", attempt + 1, batch_size, e)
                if batch_size == 10:
                    batch_size = 5  # Halve batch on first failure
                else:
                    raise  # Already at minimum, propagate error

        return []  # Should not reach here

    def _init_context_manager(self, novel: Novel) -> None:
        """Initialize the context manager for a novel."""
        bible = self._bibles.get(novel.id)
        if bible is None:
            # Load from file
            from src.storage.file_store import FileStore
            fs = FileStore()
            bible_data = fs.load_story_bible(novel.title)
            if bible_data:
                bible = StoryBibleManager.from_dict(bible_data)
            else:
                bible = StoryBibleManager(novel_id=novel.id, novel_title=novel.title)
            self._bibles[novel.id] = bible

        from src.llm.prompt_manager import PromptManager
        ctx = ContextManager(
            llm_client=self.llm,
            prompt_manager=PromptManager(),
            story_bible=bible,
        )
        self._contexts[novel.id] = ctx

    def _get_chapter_writer(self, novel: Novel):
        """Get or create a ChapterWriter for a novel.

        Lazily initializes all per-novel dependencies (context manager,
        story bible) and creates the ChapterWriter.
        """
        from src.generation.chapter_writer import ChapterWriter
        from src.llm.prompt_manager import PromptManager
        from src.storage.file_store import FileStore

        # Ensure context manager and bible are initialized
        if novel.id not in self._contexts:
            self._init_context_manager(novel)

        ctx = self._contexts[novel.id]
        bible = self._bibles[novel.id]
        fs = FileStore()

        return ChapterWriter(
            llm_client=self.llm,
            prompt_manager=PromptManager(),
            context_manager=ctx,
            story_bible=bible,
            quality_checker=self.quality_checker,
            file_store=fs,
            chapter_repo=self.chapter_repo,
            novel_repo=self.novel_repo,
            style_optimizer=self.style_optimizer,
        )

    def _get_trend_recommendation(self, trend_analyzer=None) -> dict:
        """Get genre/element recommendation from trend analyzer or config defaults.

        Args:
            trend_analyzer: Optional TrendAnalyzer instance.

        Returns:
            Dict with genre, hot_elements, confidence keys.
        """
        # Try trend analyzer first
        if trend_analyzer is not None:
            try:
                rec = trend_analyzer.recommend()
                if rec.get("genre") and rec.get("confidence", 0) > 0.2:
                    return rec
            except Exception as e:
                logger.warning("Trend recommendation failed, using defaults: %s", e)

        # Fall back to config defaults
        from src.config import AppConfig
        config = AppConfig()
        trending_tags = config.trending_tags_2025

        return {
            "genre": "玄幻",
            "reason": "默认推荐（无趋势数据）",
            "hot_elements": trending_tags[:5] if trending_tags else ["系统流", "重生", "逆袭"],
            "confidence": 0.3,
        }

    @staticmethod
    def _find_outline(outlines: list[ChapterOutline], chapter_num: int) -> Optional[ChapterOutline]:
        """Find an outline by chapter number."""
        for o in outlines:
            if o.chapter_number == chapter_num:
                return o
        return None
