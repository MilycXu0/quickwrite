"""Genre Classifier — ranks genre popularity and detects trends.

Uses exponential recency weighting to prioritize recent data
when ranking genre popularity. Tracks rising vs declining genres.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from src.data_collection.base import ScrapedBook

logger = logging.getLogger(__name__)

# Genre display names and their aliases
GENRE_ALIASES = {
    "玄幻": ["玄幻", "东方玄幻", "异界大陆", "王朝争霸"],
    "仙侠": ["仙侠", "古典仙侠", "现代修真", "洪荒", "神话修真"],
    "都市": ["都市", "都市生活", "异术超能", "重生逆袭", "系统流"],
    "科幻": ["科幻", "星际文明", "未来世界", "末世危机", "进化变异"],
    "历史": ["历史", "架空历史", "穿越古代", "历史传奇"],
    "游戏": ["游戏", "游戏异界", "电子竞技", "虚拟现实"],
    "悬疑": ["悬疑", "悬疑推理", "灵异恐怖", "盗墓探险"],
    "言情": ["言情", "现代言情", "古代言情", "纯爱"],
    "武侠": ["武侠", "传统武侠", "新武侠"],
}


class GenreClassifier:
    """Analyzes genre popularity and trends from scraped data."""

    def __init__(self, decay_days: int = 30):
        """
        Args:
            decay_days: Number of days over which exponential decay applies.
                        Recent data within this window gets higher weight.
        """
        self.decay_days = decay_days
        self._genre_counts: dict[str, int] = defaultdict(int)
        self._genre_reads: dict[str, int] = defaultdict(int)
        self._genre_books: dict[str, list[ScrapedBook]] = defaultdict(list)
        self._snapshots: list[dict] = []  # Historical snapshots for trend detection

    def process_books(self, books: list[ScrapedBook]) -> None:
        """Process a batch of books and update genre statistics."""
        now = datetime.utcnow()

        for book in books:
            genre = self._normalize_genre(book.genre)
            self._genre_counts[genre] += 1
            self._genre_reads[genre] += book.read_count
            self._genre_books[genre].append(book)

        # Store snapshot for trend analysis
        self._snapshots.append({
            "timestamp": now.isoformat(),
            "genre_counts": dict(self._genre_counts),
            "total_books": len(books),
        })

        # Keep only recent snapshots (last 60 days)
        cutoff = now - timedelta(days=60)
        self._snapshots = [
            s for s in self._snapshots
            if datetime.fromisoformat(s["timestamp"]) > cutoff
        ]

    def _normalize_genre(self, genre: str) -> str:
        """Map genre strings to canonical genre names."""
        for canonical, aliases in GENRE_ALIASES.items():
            if genre in aliases:
                return canonical
        return genre

    def get_genre_ranking(self) -> list[dict]:
        """Get genre popularity ranking based on book count.

        Returns:
            List of {genre, count, percentage, trend} sorted by popularity.
        """
        total = sum(self._genre_counts.values())
        if total == 0:
            return []

        ranking = []
        for genre, count in sorted(self._genre_counts.items(), key=lambda x: x[1], reverse=True):
            trend = self._detect_trend(genre)
            ranking.append({
                "genre": genre,
                "count": count,
                "percentage": round(count / total * 100, 1),
                "trend": trend,  # "rising", "stable", "declining", "new"
            })

        return ranking

    def _detect_trend(self, genre: str) -> str:
        """Detect if a genre is rising, stable, or declining.

        Compares recent snapshots vs older ones.
        """
        if len(self._snapshots) < 2:
            return "stable"

        # Split into recent (last 7 days) and baseline (before)
        now = datetime.utcnow()
        recent_cutoff = now - timedelta(days=7)

        recent_snapshots = [
            s for s in self._snapshots
            if datetime.fromisoformat(s["timestamp"]) > recent_cutoff
        ]
        baseline_snapshots = [
            s for s in self._snapshots
            if datetime.fromisoformat(s["timestamp"]) <= recent_cutoff
        ]

        if not recent_snapshots or not baseline_snapshots:
            return "stable"

        recent_avg = sum(s["genre_counts"].get(genre, 0) for s in recent_snapshots) / len(recent_snapshots)
        baseline_avg = sum(s["genre_counts"].get(genre, 0) for s in baseline_snapshots) / max(1, len(baseline_snapshots))

        if baseline_avg == 0:
            return "new" if recent_avg > 0 else "stable"

        change = (recent_avg - baseline_avg) / baseline_avg
        if change > 0.15:
            return "rising"
        elif change < -0.15:
            return "declining"
        else:
            return "stable"

    def get_recommended_genre(self) -> dict:
        """Get AI-recommended genre for a new novel.

        Considers: popularity, trend direction, and a randomness factor
        to avoid always picking the same genre.
        """
        ranking = self.get_genre_ranking()
        if not ranking:
            # Fallback recommendations based on 2025 trends
            return {
                "genre": "玄幻",
                "reason": "默认推荐（暂无爬取数据）",
                "hot_elements": ["系统流", "重生", "无敌流"],
                "confidence": 0.5,
            }

        # Score each genre: base popularity + trend bonus
        scored = []
        for g in ranking:
            score = g["count"]
            if g["trend"] == "rising":
                score *= 1.3
            elif g["trend"] == "new":
                score *= 1.5
            elif g["trend"] == "declining":
                score *= 0.7
            scored.append({**g, "score": round(score, 1)})

        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[0]

        return {
            "genre": top["genre"],
            "reason": f"热门程度排名第1，趋势：{top['trend']}",
            "hot_elements": self._suggest_elements(top["genre"]),
            "confidence": min(0.9, top["count"] / max(1, sum(g["count"] for g in ranking))),
            "alternatives": [g["genre"] for g in scored[1:4]],
        }

    def _suggest_elements(self, genre: str) -> list[str]:
        """Suggest hot elements for a genre based on collected data."""
        # Analyze books in this genre for common tags
        books = self._genre_books.get(genre, [])
        if not books:
            # Fallback defaults per genre
            defaults = {
                "玄幻": ["系统流", "重生", "无敌流", "修炼体系"],
                "都市": ["重生逆袭", "系统流", "鉴宝", "商战"],
                "仙侠": ["修仙2.0", "洪荒", "法宝", "天劫"],
                "科幻": ["星际文明", "基因进化", "AI觉醒"],
                "历史": ["穿越先知", "科举朝堂", "制度改革"],
                "游戏": ["游戏系统", "职业体系", "副本挑战"],
            }
            return defaults.get(genre, ["系统流", "重生", "逆袭"])

        # Count tags across books in this genre
        from collections import Counter
        tag_counter = Counter()
        for book in books:
            for tag in book.tags:
                tag_counter[tag] += 1

        return [tag for tag, _ in tag_counter.most_common(5)]

    def get_statistics(self) -> dict:
        """Get overall genre statistics."""
        ranking = self.get_genre_ranking()
        return {
            "total_books_analyzed": sum(self._genre_counts.values()),
            "genre_count": len(self._genre_counts),
            "ranking": ranking,
            "recommended": self.get_recommended_genre(),
        }

    def reset(self) -> None:
        """Reset all accumulated data."""
        self._genre_counts.clear()
        self._genre_reads.clear()
        self._genre_books.clear()
        self._snapshots.clear()
