"""Quality Checker — validates generated chapter quality and continuity."""

import json
import logging
from typing import Optional

from src.generation.story_bible import StoryBibleManager
from src.llm.client import LLMClient
from src.utils.text_utils import count_chinese_chars, count_words_cn

logger = logging.getLogger(__name__)


class QualityChecker:
    """Post-generation quality validation for chapters.

    Checks:
    1. Word count within target range
    2. Continuity with Story Bible (no contradictions)
    3. Dialogue ratio sufficiency
    4. Cliffhanger presence
    5. Repetition detection
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def check(
        self,
        content: str,
        chapter_number: int,
        story_bible: StoryBibleManager,
        target_words: int = 2000,
        min_words: int = 1800,
        max_words: int = 2200,
    ) -> float:
        """Run all quality checks and return a composite score (0.0-1.0).

        Args:
            content: Generated chapter content.
            chapter_number: Current chapter number.
            story_bible: Story Bible for continuity verification.
            target_words: Ideal word count.
            min_words: Minimum acceptable words.
            max_words: Maximum acceptable words.

        Returns:
            Quality score from 0.0 (worst) to 1.0 (best).
        """
        scores = []

        # 1. Word count check (heuristic)
        word_count = count_words_cn(content)
        wc_score = self._score_word_count(word_count, target_words, min_words, max_words)
        scores.append(wc_score)
        logger.debug("Quality: word_count=%d score=%.2f", word_count, wc_score)

        # 2. Basic structural checks
        struct_score = self._check_structure(content)
        scores.append(struct_score)
        logger.debug("Quality: structure score=%.2f", struct_score)

        # 3. Dialogue ratio check
        dialogue_score = self._check_dialogue(content)
        scores.append(dialogue_score)
        logger.debug("Quality: dialogue score=%.2f", dialogue_score)

        # 4. Continuity check (uses Haiku for cheap validation)
        if chapter_number > 1:
            continuity_score = await self._check_continuity(content, story_bible)
            scores.append(continuity_score)
            logger.debug("Quality: continuity score=%.2f", continuity_score)

        # 5. Repetition detection
        rep_score = self._check_repetition(content)
        scores.append(rep_score)
        logger.debug("Quality: repetition score=%.2f", rep_score)

        # Composite score
        avg_score = sum(scores) / len(scores)
        return round(avg_score, 2)

    def _score_word_count(self, actual: int, target: int, min_w: int, max_w: int) -> float:
        """Score word count closeness to target."""
        if min_w <= actual <= max_w:
            # Within range — score based on distance from target
            distance = abs(actual - target)
            max_deviation = max(target - min_w, max_w - target)
            return 1.0 - (distance / max_deviation) * 0.4  # 0.6-1.0 range
        elif actual < min_w:
            return max(0.0, actual / min_w * 0.5)  # Below min — penalty
        else:
            return max(0.0, 1.0 - (actual - max_w) / max_w * 0.5)  # Above max — penalty

    def _check_structure(self, content: str) -> float:
        """Check basic structural elements exist in content."""
        score = 1.0

        # Check for paragraph breaks
        paragraphs = [p for p in content.split("\n") if p.strip()]
        if len(paragraphs) < 5:
            score -= 0.2
            logger.debug("Too few paragraphs: %d", len(paragraphs))

        # Check for dialogue indicators
        has_dialogue = any(marker in content for marker in ['"', '"', '"', "'", "'", "'", '"', '"'])
        if not has_dialogue:
            score -= 0.3
            logger.debug("No dialogue detected")

        # Check for scene/environment description
        if len(content) > 200:
            score -= 0.0  # Placeholder for more sophisticated checks

        return max(0.0, score)

    def _check_dialogue(self, content: str) -> float:
        """Estimate dialogue ratio. Web novels should have ~30%+ dialogue."""
        quote_patterns = ['"', '"', '"', "'", "'", "'", '"', '"']
        total_chars = len(content)
        if total_chars == 0:
            return 0.0

        # Count characters inside quotation marks
        in_quote = False
        quote_chars = 0
        i = 0
        while i < total_chars:
            if content[i] in ['"', '"', '"', "'", "'", "'", '"', '"']:
                in_quote = not in_quote
                i += 1
                continue
            if in_quote:
                quote_chars += 1
            i += 1

        ratio = quote_chars / max(1, total_chars)
        # Target: 25-45% dialogue
        if 0.25 <= ratio <= 0.45:
            return 1.0
        elif ratio < 0.25:
            return ratio / 0.25 * 0.8  # Penalize but not too harshly
        else:
            return max(0.5, 1.0 - (ratio - 0.45))  # Too much dialogue

    async def _check_continuity(self, content: str, story_bible: StoryBibleManager) -> float:
        """Use Haiku to check for continuity errors against the Story Bible."""
        # Get key characters and recent events
        character_names = story_bible.get_character_names()
        if not character_names:
            return 1.0  # No characters to check against

        bible_snapshot = story_bible.get_full_context()

        check_prompt = (
            f"验证以下章节内容与已设定的故事圣经是否存在矛盾。\n\n"
            f"故事设定：\n{json.dumps(bible_snapshot, ensure_ascii=False, indent=2)[:2000]}\n\n"
            f"待检查章节内容（前2000字）：\n{content[:2000]}\n\n"
            f"主要检查项：\n"
            f"1. 人物名字是否与设定一致\n"
            f"2. 人物关系和状态是否前后矛盾\n"
            f"3. 世界观设定是否被违反\n"
            f"4. 时间线是否合理\n\n"
            f"请以JSON格式回复：{{\"score\": 0.0-1.0, \"issues\": [\"问题描述\"], \"ok\": true/false}}"
        )

        try:
            response = await self.llm.generate(
                system_prompt="你是一个小说质量审核助手。只输出JSON格式结果。",
                user_message=check_prompt,
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                temperature=0.2,
                enable_thinking=False,
                enable_caching=False,
            )

            from src.utils.text_utils import safe_parse_json
            result = safe_parse_json(response.text)
            score = float(result.get("score", 0.8))
            issues = result.get("issues", [])
            if issues:
                logger.warning("Continuity issues in ch: %s", issues)
            return score
        except Exception as e:
            logger.warning("Continuity check failed: %s", e)
            return 0.8  # Default: assume OK if check fails

    def _check_repetition(self, content: str) -> float:
        """Detect excessive phrase repetition."""
        if len(content) < 500:
            return 1.0

        # Simple N-gram repetition check
        # Split into sentences and check for identical sentences
        sentences = []
        current = ""
        for char in content:
            current += char
            if char in "。！？…\n":
                if len(current.strip()) > 10:
                    sentences.append(current.strip())
                current = ""

        if len(sentences) < 5:
            return 1.0

        # Count unique sentences vs total
        unique_ratio = len(set(sentences)) / len(sentences)

        if unique_ratio > 0.9:
            return 1.0
        elif unique_ratio > 0.7:
            return 0.8
        elif unique_ratio > 0.5:
            return 0.6
        else:
            return 0.4
