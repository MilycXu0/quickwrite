"""Tag Extractor — processes raw scraped tags into normalized trending elements.

Handles:
- Tag normalization (synonyms, variants)
- Tag frequency counting
- Co-occurrence matrix building
- Tag hierarchy (L1 genre → L2 subgenre → L3 specific element)
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime

from src.data_collection.base import ScrapedBook

logger = logging.getLogger(__name__)


# Tag synonym mapping — normalizes variations of the same tag
TAG_SYNONYMS = {
    "重生": ["重生", "重生流", "重生文", "重生归来", "重生之"],
    "穿越": ["穿越", "穿越者", "穿越时空", "穿书", "穿越文"],
    "系统流": ["系统流", "系统", "系统文", "金手指系统"],
    "无敌流": ["无敌流", "无敌", "无敌文", "开局无敌", "碾压"],
    "赘婿": ["赘婿", "赘婿流", "赘婿文", "上门女婿"],
    "逆袭": ["逆袭", "逆袭流", "反转人生", "咸鱼翻身"],
    "修炼": ["修炼", "修真", "修仙", "修道", "武道"],
    "无CP": ["无CP", "无cp", "无女主", "女主无CP"],
    "大女主": ["大女主", "女强", "女主文", "女频强者"],
}


class TagExtractor:
    """Extracts, normalizes, and ranks tags from scraped book data."""

    def __init__(self):
        self._tag_frequencies: Counter = Counter()
        self._co_occurrence: dict[str, Counter] = defaultdict(Counter)
        self._tag_by_category: dict[str, list[str]] = defaultdict(list)  # "金手指" -> [tags]
        self._genre_tag_map: dict[str, Counter] = defaultdict(Counter)    # genre -> tag frequencies

    def process_books(self, books: list[ScrapedBook]) -> dict:
        """Process a batch of scraped books and update tag statistics.

        Args:
            books: List of ScrapedBook objects from any source.

        Returns:
            Dict with tag statistics.
        """
        for book in books:
            # Normalize and enrich tags
            all_tags = self._normalize_tags(book.tags)
            all_tags.append(book.genre)  # Genre is a top-level tag
            if book.subgenre:
                all_tags.append(book.subgenre)

            all_tags = list(set(all_tags))  # Deduplicate per book

            # Update frequencies
            for tag in all_tags:
                self._tag_frequencies[tag] += 1
                self._genre_tag_map[book.genre][tag] += 1

            # Update co-occurrence
            for i, tag1 in enumerate(all_tags):
                for tag2 in all_tags[i + 1:]:
                    self._co_occurrence[tag1][tag2] += 1
                    self._co_occurrence[tag2][tag1] += 1

        logger.debug("Processed %d books: %d unique tags", len(books), len(self._tag_frequencies))
        return self.get_statistics()

    def _normalize_tags(self, tags: list[str]) -> list[str]:
        """Normalize tag names by resolving synonyms."""
        normalized = []
        tag_to_canonical = {}

        # Build reverse mapping
        for canonical, variants in TAG_SYNONYMS.items():
            for variant in variants:
                tag_to_canonical[variant] = canonical

        for tag in tags:
            tag = tag.strip()
            if tag in tag_to_canonical:
                normalized.append(tag_to_canonical[tag])
            else:
                normalized.append(tag)

        return normalized

    def get_top_tags(self, n: int = 30) -> list[dict]:
        """Get the top N most frequent tags."""
        return [
            {"name": tag, "frequency": count,
             "co_occurring": self._get_co_tags(tag, 5)}
            for tag, count in self._tag_frequencies.most_common(n)
        ]

    def get_tags_by_genre(self, genre: str, n: int = 10) -> list[dict]:
        """Get top tags for a specific genre."""
        genre_tags = self._genre_tag_map.get(genre, Counter())
        return [
            {"name": tag, "frequency": count}
            for tag, count in genre_tags.most_common(n)
        ]

    def _get_co_tags(self, tag: str, n: int = 5) -> list[str]:
        """Get tags that most frequently co-occur with the given tag."""
        co_tags = self._co_occurrence.get(tag, Counter())
        return [t for t, _ in co_tags.most_common(n)]

    def get_tag_co_occurrence_matrix(self, top_n: int = 20) -> dict:
        """Get a co-occurrence matrix for the top N tags."""
        top_tags = [t for t, _ in self._tag_frequencies.most_common(top_n)]
        matrix = {}
        for tag in top_tags:
            co_tags = self._co_occurrence.get(tag, Counter())
            matrix[tag] = {t: co_tags.get(t, 0) for t in top_tags if t != tag}
        return matrix

    def detect_trending_combinations(self, min_freq: int = 3) -> list[dict]:
        """Detect frequently co-occurring tag combinations (potential new tropes)."""
        combinations = []
        seen_pairs = set()

        for tag1, co_tags in self._co_occurrence.items():
            for tag2, freq in co_tags.most_common(10):
                if freq >= min_freq:
                    pair_key = tuple(sorted([tag1, tag2]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        combinations.append({
                            "elements": [tag1, tag2],
                            "frequency": freq,
                            "strength": freq / max(1, self._tag_frequencies[tag1]),
                        })

        # Sort by frequency
        combinations.sort(key=lambda x: x["frequency"], reverse=True)
        return combinations[:50]

    def get_statistics(self) -> dict:
        """Get overall tag statistics."""
        total_instances = sum(self._tag_frequencies.values())
        return {
            "total_unique_tags": len(self._tag_frequencies),
            "total_tag_instances": total_instances,
            "top_tags": self.get_top_tags(20),
            "top_combinations": self.detect_trending_combinations()[:10],
        }

    def reset(self) -> None:
        """Reset all accumulated statistics."""
        self._tag_frequencies.clear()
        self._co_occurrence.clear()
        self._tag_by_category.clear()
        self._genre_tag_map.clear()
