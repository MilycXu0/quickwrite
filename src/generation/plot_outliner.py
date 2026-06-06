"""Plot Outliner — designs chapter-by-chapter plot structure."""

import json
import logging
from typing import Optional

from src.core.models import ChapterOutline
from src.llm.client import LLMClient
from src.llm.prompt_manager import PromptManager

logger = logging.getLogger(__name__)


class PlotOutliner:
    """Generates chapter-level outlines for a batch of chapters.

    Uses Claude Opus for structural plotting with structured output.
    Can be called for initial outlining and on-demand for the next batch.
    """

    OUTLINE_BATCH_SIZE = 10  # Generate 10 chapters at a time (fits in 16K tokens)

    def __init__(self, llm_client: LLMClient, prompt_manager: PromptManager):
        self.llm = llm_client
        self.prompts = prompt_manager

    async def generate_outlines(
        self,
        novel_title: str,
        genre: str,
        world_summary: str,
        protagonist_name: str,
        protagonist_state: str,
        active_plots: str,
        recent_events: str,
        start_chapter: int = 1,
        end_chapter: Optional[int] = None,
        model: Optional[str] = None,
    ) -> list[ChapterOutline]:
        """Generate chapter outlines for a range of chapters.

        Args:
            novel_title: Name of the novel.
            genre: Primary genre.
            world_summary: Brief world setting summary.
            protagonist_name: Name of the protagonist.
            protagonist_state: Current state of the protagonist.
            active_plots: Active plot threads.
            recent_events: Recent story events.
            start_chapter: First chapter number to outline.
            end_chapter: Last chapter number (defaults to start + BATCH_SIZE - 1).
            model: Override the default model.

        Returns:
            List of ChapterOutline objects.
        """
        if end_chapter is None:
            end_chapter = start_chapter + self.OUTLINE_BATCH_SIZE - 1

        model = model or "claude-opus-4-8-20251101"

        logger.info("Generating outlines for chapters %d-%d of '%s'", start_chapter, end_chapter, novel_title)

        system_prompt = self.prompts.render_system(
            "chapter_outline",
            novel_title=novel_title,
            genre=genre,
            world_summary=world_summary,
            protagonist_name=protagonist_name,
        )
        user_prompt = self.prompts.render_user(
            "chapter_outline",
            novel_title=novel_title,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            protagonist_state=protagonist_state,
            active_plots=active_plots,
            recent_events=recent_events,
        )

        response = await self.llm.generate(
            system_prompt=system_prompt,
            user_message=user_prompt,
            model=model,
            max_tokens=16384,
            temperature=0.7,
            enable_thinking=True,
            thinking_budget=2048,
            enable_caching=False,
        )

        from src.utils.text_utils import safe_parse_json
        data = safe_parse_json(response.text)
        outlines = []

        for ch_data in data.get("chapters", []):
            outline = ChapterOutline(
                chapter_number=ch_data.get("chapter_number", 0),
                title=ch_data.get("title", ""),
                bullet_points=ch_data.get("bullet_points", []),
                pov_character=ch_data.get("pov_character", protagonist_name),
                cliffhanger=ch_data.get("cliffhanger", ""),
                characters_appearing=ch_data.get("characters_appearing", []),
            )
            outlines.append(outline)

        logger.info("Generated %d chapter outlines", len(outlines))
        return outlines

    def _parse_response(self, text: str) -> dict:
        """Extract and parse JSON from the LLM response."""
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
                return json.loads(match.group())
            raise ValueError(f"Could not parse outline output: {text[:500]}")
