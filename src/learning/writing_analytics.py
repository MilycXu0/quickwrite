"""Writing Analytics — analyzes generated chapters to extract improvement insights.

Runs periodically to:
1. Score trends over time (is quality improving?)
2. Identify high-scoring patterns (what makes a chapter good?)
3. Detect common issues in low-scoring chapters
4. Generate actionable improvement suggestions
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.learning.knowledge_base import KnowledgeBase
from src.llm.client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class ChapterMetrics:
    """Aggregated metrics for a single chapter."""
    chapter_number: int
    title: str
    word_count: int
    quality_score: float
    genre: str = ""
    elements: list[str] = field(default_factory=list)
    dialogue_ratio: float = 0.0
    status: str = ""


@dataclass
class AnalysisReport:
    """Result of a full writing analysis cycle."""
    cycle: int
    timestamp: str
    total_chapters_analyzed: int
    quality_trend: str          # "improving", "stable", "declining"
    avg_quality: float
    best_chapter: Optional[dict] = None
    worst_chapter: Optional[dict] = None
    improvement_suggestions: list[str] = field(default_factory=list)
    learned_patterns: list[dict] = field(default_factory=list)
    genre_insights: dict = field(default_factory=dict)


class WritingAnalytics:
    """Analyzes writing output to drive continuous improvement."""

    MIN_CHAPTERS_FOR_ANALYSIS = 3

    def __init__(
        self,
        llm_client: LLMClient,
        knowledge_base: KnowledgeBase,
        chapter_repo=None,
        novel_repo=None,
    ):
        self.llm = llm_client
        self.kb = knowledge_base
        self.chapter_repo = chapter_repo
        self.novel_repo = novel_repo

    # ── Main Analysis Pipeline ──────────────────────────

    async def run_analysis_cycle(self) -> AnalysisReport:
        """Run a full analysis cycle across all novels and chapters.

        Returns an AnalysisReport with findings and suggestions.
        """
        cycle = self.kb._data["total_learning_cycles"] + 1
        logger.info("=" * 60)
        logger.info("Learning Cycle #%d — Analyzing writing patterns...", cycle)
        logger.info("=" * 60)

        # 1. Collect metrics from all completed chapters
        metrics = self._collect_chapter_metrics()
        if len(metrics) < self.MIN_CHAPTERS_FOR_ANALYSIS:
            logger.info("Not enough chapters for analysis (%d < %d)",
                        len(metrics), self.MIN_CHAPTERS_FOR_ANALYSIS)
            return AnalysisReport(
                cycle=cycle,
                timestamp=datetime.utcnow().isoformat(),
                total_chapters_analyzed=len(metrics),
                quality_trend="insufficient_data",
                avg_quality=0.0,
            )

        # 2. Statistical analysis
        quality_trend, avg_q = self._analyze_quality_trend(metrics)
        best, worst = self._find_extremes(metrics)

        # 3. LLM-powered deep analysis
        insights = await self._deep_analysis(metrics)

        # 4. Update knowledge base
        self._update_knowledge_base(metrics, insights, cycle)

        # 5. Generate improvement suggestions
        suggestions = self._generate_suggestions(metrics, insights)

        report = AnalysisReport(
            cycle=cycle,
            timestamp=datetime.utcnow().isoformat(),
            total_chapters_analyzed=len(metrics),
            quality_trend=quality_trend,
            avg_quality=round(avg_q, 2),
            best_chapter=best,
            worst_chapter=worst,
            improvement_suggestions=suggestions,
            learned_patterns=insights.get("patterns", []),
            genre_insights=insights.get("genre_insights", {}),
        )

        self.kb._data["total_learning_cycles"] = cycle
        self.kb.save()

        logger.info("Learning Cycle #%d complete. Quality trend: %s, Avg: %.2f",
                    cycle, quality_trend, avg_q)
        return report

    # ── Data Collection ─────────────────────────────────

    def _collect_chapter_metrics(self) -> list[ChapterMetrics]:
        """Collect metrics from all chapters across all novels."""
        metrics = []
        if not self.chapter_repo or not self.novel_repo:
            return metrics

        novels = self.novel_repo.list_all()
        for novel in novels:
            chapters = self.chapter_repo.list_by_novel(novel.id)
            for ch in chapters:
                if ch.status != "completed" or ch.word_count == 0:
                    continue
                # Read content for dialogue analysis
                dialogue_ratio = 0.0
                if ch.content_path and Path(ch.content_path).exists():
                    try:
                        with open(ch.content_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        from src.utils.text_utils import extract_dialogue_ratio
                        dialogue_ratio = extract_dialogue_ratio(content)
                    except Exception:
                        pass

                elements = []
                if novel.trending_elements:
                    elements = novel.trending_elements.get("tags", [])

                metrics.append(ChapterMetrics(
                    chapter_number=ch.chapter_number,
                    title=ch.title or "",
                    word_count=ch.word_count,
                    quality_score=ch.quality_score or 0.0,
                    genre=novel.genre,
                    elements=elements,
                    dialogue_ratio=dialogue_ratio,
                    status=ch.status,
                ))

        return metrics

    # ── Statistical Analysis ────────────────────────────

    def _analyze_quality_trend(self, metrics: list[ChapterMetrics]) -> tuple[str, float]:
        """Determine if quality is improving, stable, or declining."""
        if len(metrics) < 2:
            return "insufficient_data", metrics[0].quality_score if metrics else 0.0

        sorted_m = sorted(metrics, key=lambda m: m.chapter_number)
        first_half = sorted_m[:len(sorted_m) // 2]
        second_half = sorted_m[len(sorted_m) // 2:]

        first_avg = sum(m.quality_score for m in first_half) / len(first_half)
        second_avg = sum(m.quality_score for m in second_half) / len(second_half)
        overall_avg = sum(m.quality_score for m in metrics) / len(metrics)

        diff = second_avg - first_avg
        if diff > 0.05:
            trend = "improving"
        elif diff < -0.05:
            trend = "declining"
        else:
            trend = "stable"

        return trend, overall_avg

    def _find_extremes(self, metrics: list[ChapterMetrics]) -> tuple[Optional[dict], Optional[dict]]:
        """Find best and worst chapters."""
        if not metrics:
            return None, None

        sorted_by_q = sorted(metrics, key=lambda m: m.quality_score, reverse=True)
        best = sorted_by_q[0]
        worst = sorted_by_q[-1]

        def _to_dict(m: ChapterMetrics) -> dict:
            return {
                "chapter_number": m.chapter_number,
                "title": m.title,
                "word_count": m.word_count,
                "quality_score": m.quality_score,
                "genre": m.genre,
                "dialogue_ratio": round(m.dialogue_ratio, 2),
            }

        return _to_dict(best), _to_dict(worst)

    # ── LLM Deep Analysis ───────────────────────────────

    async def _deep_analysis(self, metrics: list[ChapterMetrics]) -> dict:
        """Use Haiku to deeply analyze writing patterns and generate insights."""
        # Prepare summary data for the LLM
        high_q = [m for m in metrics if m.quality_score >= 0.75]
        low_q = [m for m in metrics if m.quality_score <= 0.5]

        summary = {
            "total_chapters": len(metrics),
            "avg_quality": round(sum(m.quality_score for m in metrics) / len(metrics), 2),
            "avg_word_count": round(sum(m.word_count for m in metrics) / len(metrics)),
            "high_quality_count": len(high_q),
            "low_quality_count": len(low_q),
            "genres": list(set(m.genre for m in metrics)),
        }

        # Build a prompt for Haiku
        prompt = (
            "你是一个小说写作质量分析师。根据以下写作数据，总结：\n"
            "1. 成功模式（高分章节的共性）\n"
            "2. 待改进点（低分章节的共性问题）\n"
            "3. 类型特定建议\n"
            "4. 3-5 条可操作的具体改进建议\n\n"
            f"写作数据：{json.dumps(summary, ensure_ascii=False)}\n\n"
            "请以 JSON 格式回复：\n"
            '{"patterns": [{"name": "模式名", "description": "描述", "evidence": "证据"}], '
            '"genre_insights": {"类型名": {"strength": "优势", "weakness": "短板"}}, '
            '"suggestions": ["建议1", "建议2", ...]}'
        )

        try:
            response = await self.llm.generate(
                system_prompt="你是写作质量分析专家，输出纯 JSON，不包含任何额外文字。",
                user_message=prompt,
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                temperature=0.3,
                enable_thinking=False,
                enable_caching=False,
            )

            from src.utils.text_utils import safe_parse_json
            return safe_parse_json(response.text)
        except Exception as e:
            logger.warning("Deep analysis LLM call failed: %s", e)
            return {"patterns": [], "genre_insights": {}, "suggestions": []}

    # ── Knowledge Update ────────────────────────────────

    def _update_knowledge_base(
        self, metrics: list[ChapterMetrics], insights: dict, cycle: int
    ) -> None:
        """Update the knowledge base with new findings."""
        # Per-genre updates
        genres = {}
        for m in metrics:
            if m.genre not in genres:
                genres[m.genre] = []
            genres[m.genre].append(m)

        for genre, genre_metrics in genres.items():
            avg_q = sum(m.quality_score for m in genre_metrics) / len(genre_metrics)
            avg_dialogue = sum(m.dialogue_ratio for m in genre_metrics) / len(genre_metrics)
            avg_words = sum(m.word_count for m in genre_metrics) / len(genre_metrics)

            high = [m for m in genre_metrics if m.quality_score >= 0.7]

            # Extract successful elements from high-scoring chapters
            element_scores = {}
            for m in high:
                for elem in m.elements:
                    if elem not in element_scores:
                        element_scores[elem] = []
                    element_scores[elem].append(m.quality_score)

            successful_elements = [
                elem for elem, scores in sorted(
                    element_scores.items(),
                    key=lambda x: sum(x[1]) / len(x[1]),
                    reverse=True
                )[:5]
                if len(scores) >= 2 and (sum(scores) / len(scores)) >= 0.7
            ]

            self.kb.update_genre_knowledge(genre, {
                "chapter_count": len(genre_metrics),
                "avg_quality": avg_q,
                "optimal_word_count": int(avg_words),
                "optimal_dialogue_ratio": round(avg_dialogue, 2),
                "successful_elements": successful_elements,
            })

        # Global tips from LLM insights
        for suggestion in insights.get("suggestions", []):
            self.kb.add_global_tip(suggestion)

        # Best patterns
        patterns = insights.get("patterns", [])
        for pattern in patterns[:3]:
            self.kb.add_global_tip(
                f"[{pattern.get('name', '模式')}] {pattern.get('description', '')}"
            )

        # Record evolution
        self.kb.record_evolution({
            "chapters_analyzed": len(metrics),
            "avg_quality": round(sum(m.quality_score for m in metrics) / len(metrics), 2),
            "new_patterns": len(patterns),
            "suggestions_added": len(insights.get("suggestions", [])),
        })

        # Update top elements
        element_performance = []
        element_scores_all = {}
        for m in metrics:
            for elem in m.elements:
                if elem not in element_scores_all:
                    element_scores_all[elem] = []
                element_scores_all[elem].append(m.quality_score)

        for elem, scores in element_scores_all.items():
            if len(scores) >= 2:
                element_performance.append({
                    "element": elem,
                    "avg_quality": round(sum(scores) / len(scores), 2),
                    "usage_count": len(scores),
                })

        self.kb.update_top_elements(element_performance)

    # ── Suggestion Generation ───────────────────────────

    def _generate_suggestions(
        self, metrics: list[ChapterMetrics], insights: dict
    ) -> list[str]:
        """Generate actionable improvement suggestions."""
        suggestions = list(insights.get("suggestions", []))

        # Add data-driven suggestions
        avg_words = sum(m.word_count for m in metrics) / len(metrics) if metrics else 0
        if avg_words < 1500:
            suggestions.append("章节偏短，建议目标字数提高到 2000-2500 字以增加内容深度")
        elif avg_words > 3000:
            suggestions.append("章节偏长，建议控制在 2000-2500 字以保持读者注意力")

        avg_dialogue = sum(m.dialogue_ratio for m in metrics) / len(metrics) if metrics else 0
        if avg_dialogue < 0.2:
            suggestions.append("对话比例偏低（<20%），增加角色对话可提升代入感")
        elif avg_dialogue > 0.5:
            suggestions.append("对话比例偏高（>50%），适当增加叙述和环境描写以平衡节奏")

        return suggestions[:8]  # Keep top 8
