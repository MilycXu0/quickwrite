"""World Builder — generates the fictional world setting for a novel."""

import json
import logging
from typing import Optional

from src.core.models import WorldSetting
from src.llm.client import LLMClient
from src.llm.prompt_manager import PromptManager

logger = logging.getLogger(__name__)


class WorldBuilder:
    """Generates a rich, internally consistent fictional world for a novel.

    Uses Claude Opus for deep creative world-building with structured output.
    """

    def __init__(self, llm_client: LLMClient, prompt_manager: PromptManager):
        self.llm = llm_client
        self.prompts = prompt_manager

    async def build(
        self,
        genre: str,
        trending_elements: list[str],
        extra_requirements: str = "",
        model: Optional[str] = None,
    ) -> WorldSetting:
        """Generate a complete world setting.

        Args:
            genre: Primary genre (玄幻, 都市, etc.).
            trending_elements: Hot elements to incorporate.
            extra_requirements: Any additional constraints or requests.
            model: Override the default model.

        Returns:
            Structured WorldSetting object.
        """
        trending_str = ", ".join(trending_elements) if trending_elements else "经典热门元素"
        model = model or "claude-opus-4-8-20251101"

        logger.info("Building world for genre=%s with elements=%s", genre, trending_str)

        system_prompt = self.prompts.render_system(
            "world_building",
            genre=genre,
            trending_elements=trending_str,
        )
        user_prompt = self.prompts.render_user(
            "world_building",
            genre=genre,
            trending_elements=trending_str,
            extra_requirements=extra_requirements or "无额外要求，请充分发挥创意。",
        )

        response = await self.llm.generate(
            system_prompt=system_prompt,
            user_message=user_prompt,
            model=model,
            max_tokens=8192,
            temperature=0.8,
            enable_thinking=True,
            thinking_budget=2048,
            enable_caching=False,  # One-time call, no caching benefit
        )

        # Parse JSON response
        from src.utils.text_utils import safe_parse_json
        world_data = safe_parse_json(response.text)
        world = WorldSetting(**world_data)

        logger.info("World built: %s (%s)", world.world_name, world.world_type)
        return world

    def _parse_response(self, text: str) -> dict:
        """Extract and parse JSON from the LLM response."""
        # Try to find JSON block
        text = text.strip()

        # Remove markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group())
            logger.error("Failed to parse world-building JSON from response")
            raise ValueError(f"Could not parse world-building output: {text[:500]}")
