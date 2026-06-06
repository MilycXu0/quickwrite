"""Chapter Writer — the core chapter generation engine.

This is the heart of the novel generation system. It orchestrates:
1. Context assembly from Story Bible + Context Manager
2. LLM generation with prompt caching
3. Post-generation quality checks
4. Story Bible update after successful generation
"""

import logging
from datetime import datetime
from typing import Optional

from src.core.models import Chapter, ChapterOutline, ChapterStatus, GenerationLog, Novel
from src.generation.context_manager import ContextManager
from src.generation.quality_checker import QualityChecker
from src.generation.story_bible import StoryBibleManager
from src.llm.client import LLMClient, LLMResponse
from src.llm.prompt_manager import PromptManager
from src.storage.file_store import FileStore
from src.storage.repositories.chapter_repo import ChapterRepository
from src.storage.repositories.novel_repo import NovelRepository

logger = logging.getLogger(__name__)


class ChapterWriter:
    """Generates a single chapter of a novel with full context management."""

    def __init__(
        self,
        llm_client: LLMClient,
        prompt_manager: PromptManager,
        context_manager: ContextManager,
        story_bible: StoryBibleManager,
        quality_checker: QualityChecker,
        file_store: FileStore,
        chapter_repo: ChapterRepository,
        novel_repo: NovelRepository,
        style_optimizer=None,  # Optional learning system
    ):
        self.llm = llm_client
        self.prompts = prompt_manager
        self.context = context_manager
        self.bible = story_bible
        self.quality = quality_checker
        self.files = file_store
        self.chapter_repo = chapter_repo
        self.novel_repo = novel_repo
        self.optimizer = style_optimizer

    async def write_chapter(
        self,
        novel: Novel,
        outline: ChapterOutline,
        model: Optional[str] = None,
        special_instructions: str = "",
    ) -> tuple[Chapter, str]:
        """Write a single chapter.

        Args:
            novel: The Novel model object.
            outline: ChapterOutline with title, bullet points, cliffhanger, etc.
            model: Override model for this chapter.
            special_instructions: Extra writing instructions.

        Returns:
            Tuple of (Chapter ORM object, chapter content text).

        Raises:
            RuntimeError: If generation fails after max retries.
        """
        chapter_number = outline.chapter_number

        # Use style optimizer for model/temperature recommendations
        recent_q = None
        if self.optimizer:
            recent_ch = self.chapter_repo.get_recent(novel.id, limit=1)
            if recent_ch:
                recent_q = recent_ch[0].quality_score

        model = model or (
            self.optimizer.recommend_model(novel.genre, chapter_number, recent_q)
            if self.optimizer
            else "claude-sonnet-4-6-20250514"
        )

        temp = (
            self.optimizer.recommend_temperature(novel.genre)
            if self.optimizer
            else 0.8
        )

        logger.info("Writing chapter %d: '%s' (model=%s, temp=%.2f)", chapter_number, outline.title, model, temp)

        # ── Upsert chapter record ─────────────────────────
        chapter = Chapter(
            novel_id=novel.id,
            chapter_number=chapter_number,
            title=outline.title,
            status=ChapterStatus.GENERATING.value,
            outline=outline.model_dump(),
        )
        chapter = self.chapter_repo.upsert(chapter)

        # ── Assemble context ─────────────────────────────
        ctx = self.context.assemble(
            novel_title=novel.title,
            genre=novel.genre,
            chapter_number=chapter_number,
            chapter_title=outline.title,
            chapter_outline=self._format_outline(outline),
            pov_character=outline.pov_character,
            characters_appearing=", ".join(outline.characters_appearing),
            target_words=2000,
            special_instructions=special_instructions,
        )

        # Inject learning context if optimizer available
        if self.optimizer:
            learning_ctx = self.optimizer.get_compact_context(novel.genre)
            if learning_ctx:
                ctx.system_prompt += f"\n\n[学习经验]\n{learning_ctx}"

        # ── Generate ─────────────────────────────────────
        response = await self.llm.generate(
            system_prompt=ctx.system_prompt,
            user_message=ctx.user_prompt,
            model=model,
            max_tokens=4096,
            temperature=temp,
            enable_thinking=True,
            thinking_budget=1024,
            enable_caching=True,
            stream=True,
        )

        chapter_content = response.text.strip()

        # ── Quality Checks ───────────────────────────────
        quality_score = await self.quality.check(
            content=chapter_content,
            chapter_number=chapter_number,
            story_bible=self.bible,
            target_words=2000,
        )

        # ── Post-generation processing ───────────────────
        # Generate summary for this chapter
        summary = await self.context.summarize_chapter(chapter_number, chapter_content)

        # Save to file
        filepath = self.files.save_chapter(
            novel_title=novel.title,
            chapter_number=chapter_number,
            chapter_title=outline.title,
            content=chapter_content,
        )

        # Update chapter record
        word_count = len(chapter_content.replace("\n", "").replace(" ", ""))
        self.chapter_repo.update_content(
            chapter_id=chapter.id,
            content_path=str(filepath),
            word_count=word_count,
            summary=summary,
            quality_score=quality_score,
        )

        # Update Story Bible
        self.bible.add_event(chapter_number, outline.bullet_points[0] if outline.bullet_points else "章节完成")
        self.bible.post_chapter_update(chapter_number)

        # Save updated bible to file
        self.files.save_story_bible(novel.title, self.bible.to_dict())

        # Increment novel chapter count
        self.novel_repo.increment_chapters(novel.id)

        # Log generation
        self._log_generation(novel.id, chapter.id, response, quality_score)

        logger.info(
            "Chapter %d completed: %d words, score=%.2f, cost=$%.4f",
            chapter_number, word_count, quality_score, response.cost_usd,
        )

        return chapter, chapter_content

    def _format_outline(self, outline: ChapterOutline) -> str:
        """Format a chapter outline for the prompt."""
        lines = [f"章节标题：{outline.title}"]
        lines.append("剧情要点：")
        for i, point in enumerate(outline.bullet_points, 1):
            lines.append(f"  {i}. {point}")
        lines.append(f"\n结尾钩子：{outline.cliffhanger}")
        return "\n".join(lines)

    def _log_generation(
        self,
        novel_id: int,
        chapter_id: int,
        response: LLMResponse,
        quality_score: float,
    ) -> None:
        """Record generation metrics for cost and performance tracking."""
        log_entry = GenerationLog(
            novel_id=novel_id,
            chapter_id=chapter_id,
            stage="chapter_writing",
            model_used=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cache_read_tokens=response.cache_read_tokens,
            cache_write_tokens=response.cache_write_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            success=1,
        )
        # Add to session via chapter_repo's session
        self.chapter_repo.session.add(log_entry)
        self.chapter_repo.session.commit()
