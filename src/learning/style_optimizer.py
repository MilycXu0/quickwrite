"""Style Optimizer — applies learned knowledge to improve writing prompts."""

import logging
from typing import Optional

from src.learning.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)


class StyleOptimizer:
    """Optimizes writing style based on accumulated learning.

    Provides a dynamic "learning context" string injected into system prompts
    at chapter generation time, without modifying the base YAML templates.
    """

    def __init__(self, knowledge_base: KnowledgeBase):
        self.kb = knowledge_base
        self._history: list[dict] = []

    def get_learning_context(self, genre: str) -> str:
        """Full learning context for injection into chapter writing prompts."""
        return self.kb.get_learning_context(genre)

    def get_compact_context(self, genre: str) -> str:
        """Compact 1-2 line hint for tight token budgets."""
        gk = self.kb.get_genre_knowledge(genre)
        tips = self.kb.get_global_tips(1)
        parts = []
        if gk.get("best_practices"):
            parts.append(f"最佳: {gk['best_practices'][0][:60]}")
        if tips:
            parts.append(tips[0][:80])
        return " | ".join(parts) if parts else ""

    def recommend_model(self, genre: str, chapter_number: int,
                        recent_quality: Optional[float] = None) -> str:
        """Recommend model based on recent quality trends."""
        if chapter_number % 10 == 0:
            return "claude-opus-4-8-20251101"
        if recent_quality is not None and recent_quality < 0.6:
            return "claude-opus-4-8-20251101"
        return "claude-sonnet-4-6-20250514"

    def recommend_temperature(self, quality_trend: str = "stable") -> float:
        """Recommend temperature based on quality trend."""
        if quality_trend == "declining":
            return 0.65
        elif quality_trend == "improving":
            return 0.85
        return 0.8
