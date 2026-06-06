"""Character Designer — creates the cast of characters for a novel."""

import json
import logging
from typing import Optional

from src.llm.client import LLMClient
from src.llm.prompt_manager import PromptManager

logger = logging.getLogger(__name__)


class CharacterDesigner:
    """Designs protagonists, supporting cast, and antagonists for a novel.

    Uses Claude Opus for nuanced character creation with structured output.
    """

    def __init__(self, llm_client: LLMClient, prompt_manager: PromptManager):
        self.llm = llm_client
        self.prompts = prompt_manager

    async def design(
        self,
        genre: str,
        world_summary: str,
        trending_elements: list[str],
        core_conflict: str = "",
        model: Optional[str] = None,
    ) -> dict:
        """Design the full character roster.

        Args:
            genre: Primary genre.
            world_summary: Summary of the world setting.
            trending_elements: Hot elements to reflect in character design.
            core_conflict: Central conflict idea (optional).
            model: Override the default model.

        Returns:
            Dict with protagonist, supporting_characters, antagonists, relationship_map.
        """
        trending_str = ", ".join(trending_elements) if trending_elements else "经典人设"
        audience = self._get_audience_expectations(genre)
        model = model or "claude-opus-4-8-20251101"

        logger.info("Designing characters for genre=%s", genre)

        system_prompt = self.prompts.render_system(
            "character_design",
            world_summary=world_summary,
            genre=genre,
            audience_expectations=audience,
        )
        user_prompt = self.prompts.render_user(
            "character_design",
            genre=genre,
            world_summary=world_summary,
            trending_elements=trending_str,
            core_conflict=core_conflict or "由你来设计最合适的核心冲突",
        )

        response = await self.llm.generate(
            system_prompt=system_prompt,
            user_message=user_prompt,
            model=model,
            max_tokens=8192,
            temperature=0.8,
            enable_thinking=True,
            thinking_budget=2048,
            enable_caching=False,
        )

        from src.utils.text_utils import safe_parse_json
        characters = safe_parse_json(response.text)
        char_count = (
            (1 if characters.get("protagonist") else 0)
            + len(characters.get("supporting_characters", []))
            + len(characters.get("antagonists", []))
        )
        logger.info("Characters designed: %d total", char_count)
        return characters

    def _get_audience_expectations(self, genre: str) -> str:
        """Get audience expectations for a genre."""
        expectations = {
            "玄幻": "主角成长线清晰，战斗描写精彩，修炼突破爽点密集，势力对抗宏大",
            "仙侠": "道法意境深远，因果轮回主题，仙凡之别有张力，法宝描写详细",
            "都市": "代入感强，现实逆袭爽点，商战/感情线交织，节奏明快",
            "科幻": "科技设定自洽，宏大宇宙观，文明碰撞精彩，科幻感强",
            "历史": "历史考据感，朝堂权谋精彩，穿越优势发挥，制度变革合理",
            "游戏": "游戏机制清晰，升级打怪爽感，装备/技能体系完整，竞技感强",
            "悬疑": "推理逻辑严密，恐怖氛围到位，反转令人意外，节奏紧凑",
        }
        return expectations.get(genre, "节奏明快，爽点密集，角色鲜明")

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
            raise ValueError(f"Could not parse character design output: {text[:500]}")
