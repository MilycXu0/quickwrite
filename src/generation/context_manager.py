"""Context Manager — assembles hierarchical context for LLM chapter generation.

This is the most critical module for long-form fiction continuity.
It builds a layered context from the Story Bible, recent chapters,
chapter summaries, and arc summaries to fit within the model's context window
while preserving maximal narrative coherence.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.generation.story_bible import StoryBibleManager
from src.llm.client import LLMClient, LLMResponse
from src.llm.prompt_manager import PromptManager

logger = logging.getLogger(__name__)


@dataclass
class ChapterContext:
    """Assembled context for generating a single chapter."""
    system_prompt: str
    user_prompt: str
    estimated_tokens: int


class ContextManager:
    """Assembles and manages the hierarchical context for chapter generation.

    Context Layers (in order of priority):
    Layer 1: Story Bible (world, characters, plot threads, timeline) — ALWAYS included
    Layer 2: Recent full chapters (last 3) — full text
    Layer 3: Chapter summaries (chapters 4 through N-3) — ~100 words each
    Layer 4: Arc summaries (older content) — one paragraph per completed arc
    Layer 5: Current chapter outline + appearing characters

    Prompt caching is used on Layers 1-4 (system prompt) to reduce cost
    when generating multiple chapters within the cache TTL window (1 hour).
    """

    RECENT_FULL_CHAPTERS = 3
    MAX_SUMMARIES = 90
    SUMMARY_TARGET_WORDS = 100

    def __init__(
        self,
        llm_client: LLMClient,
        prompt_manager: PromptManager,
        story_bible: StoryBibleManager,
    ):
        self.llm = llm_client
        self.prompts = prompt_manager
        self.bible = story_bible

        # Cached components
        self._recent_chapters: list[str] = []
        self._chapter_summaries: dict[int, str] = {}
        self._arc_summaries: str = ""

    # ── Chapter Content Cache ───────────────────────────

    def add_chapter(self, chapter_number: int, content: str) -> None:
        """Add a newly generated chapter to the context cache.

        Maintains the sliding window:
        - Full text for the last 3 chapters
        - Summary for chapters 4-N
        - Arc summary for very old content
        """
        # Add to recent full chapters
        self._recent_chapters.append(content)
        if len(self._recent_chapters) > self.RECENT_FULL_CHAPTERS:
            # Demote oldest full chapter to summary tier
            oldest_full = self._recent_chapters.pop(0)
            # Summary will be generated asynchronously via story bible

        # Store in bible's chapter summaries
        self.bible.add_chapter_summary(chapter_number, "")

    async def summarize_chapter(self, chapter_number: int, content: str) -> str:
        """Generate a summary for a chapter using Haiku (cheap)."""
        prompt = (
            f"请用约{self.SUMMARY_TARGET_WORDS}字总结以下小说章节的核心内容，"
            f"仅涵盖关键情节推进、角色变化和重要对话：\n\n{content[:3000]}"
        )

        try:
            response = await self.llm.generate(
                system_prompt="你是一个专业的章节摘要助手。只输出摘要内容，不要任何额外说明。",
                user_message=prompt,
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                temperature=0.3,
                enable_thinking=False,
                enable_caching=False,
            )
            summary = response.text.strip()
            self._chapter_summaries[chapter_number] = summary
            self.bible.add_chapter_summary(chapter_number, summary)
            logger.debug("Summarized chapter %d: %d chars", chapter_number, len(summary))
            return summary
        except Exception as e:
            logger.warning("Failed to summarize chapter %d: %s", chapter_number, e)
            fallback = f"第{chapter_number}章内容。"
            self._chapter_summaries[chapter_number] = fallback
            return fallback

    # ── Context Assembly ────────────────────────────────

    def assemble(
        self,
        novel_title: str,
        genre: str,
        chapter_number: int,
        chapter_title: str,
        chapter_outline: str,
        pov_character: str,
        characters_appearing: str,
        target_words: int,
        special_instructions: str = "",
    ) -> ChapterContext:
        """Assemble the full context for generating a chapter.

        Args:
            novel_title: Name of the novel.
            genre: Primary genre.
            chapter_number: Current chapter number.
            chapter_title: Title of the chapter.
            chapter_outline: Bullet points for this chapter.
            pov_character: Point-of-view character name.
            characters_appearing: Comma-separated list of characters in this chapter.
            target_words: Target word count.
            special_instructions: Any additional instructions.

        Returns:
            ChapterContext with assembled system and user prompts.
        """
        # Layer 1-4: System prompt (cached via Anthropic prompt caching)
        bible_context = self.bible.get_full_context()

        # Recent summaries from bible
        recent_summaries = self.bible.get_recent_summaries(count=10)

        # Recent full chapters
        recent_chapters_text = self._format_recent_chapters()

        system_prompt = self.prompts.render_system(
            "chapter_write",
            novel_title=novel_title,
            genre=genre,
            world_setting=bible_context["world_setting"],
            character_states=bible_context["character_states"],
            active_plot_threads=bible_context["active_plot_threads"],
            timeline=bible_context["timeline"],
            recent_summaries=recent_summaries,
            recent_chapters=recent_chapters_text,
            target_words=target_words,
        )

        # Layer 5: User prompt (varies per chapter)
        user_prompt = self.prompts.render_user(
            "chapter_write",
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            chapter_outline=chapter_outline,
            pov_character=pov_character,
            characters_appearing=characters_appearing,
            special_instructions=special_instructions or "正常发挥，确保章节质量。",
        )

        # Rough token estimation (Chinese: ~2 chars per token, English: ~4 chars per token)
        total_chars = len(system_prompt) + len(user_prompt)
        estimated_tokens = total_chars // 2

        logger.info(
            "Assembled context for ch.%d: system=%d chars, user=%d chars, ~%d tokens",
            chapter_number, len(system_prompt), len(user_prompt), estimated_tokens,
        )

        return ChapterContext(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            estimated_tokens=estimated_tokens,
        )

    def _format_recent_chapters(self) -> str:
        """Format recent full chapters for context inclusion."""
        if not self._recent_chapters:
            return "（尚无已完成的章节）"

        lines = []
        for i, content in enumerate(self._recent_chapters):
            # The most recent chapter is the last one
            chapter_num_offset = len(self._recent_chapters) - i - 1
            lines.append(f"--- 倒数第{chapter_num_offset + 1}章 ---")
            # Truncate very long chapters to ~3000 chars in context
            if len(content) > 3000:
                lines.append(content[:3000] + "\n...（已截断）")
            else:
                lines.append(content)
            lines.append("")
        return "\n".join(lines)
