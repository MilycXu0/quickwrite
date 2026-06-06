"""Knowledge Base — accumulated writing wisdom from all generated chapters.

Persists genre-specific best practices, successful patterns, and learned
improvements to a JSON file. Updated after each learning cycle.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """Persistent store of accumulated writing knowledge.

    Tracks per-genre:
    - Best practices (from high-scoring chapters)
    - Common pitfalls (from low-scoring chapters)
    - Optimal parameters (word count, dialogue ratio, pacing)
    - Successful element combinations
    - Style evolution over time
    """

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent / "data" / "knowledge"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.kb_path = self.data_dir / "writing_knowledge.json"
        self._data = self._load()

    def _load(self) -> dict:
        """Load knowledge base from disk."""
        if self.kb_path.exists():
            try:
                with open(self.kb_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupted knowledge base, starting fresh")
        return self._default_kb()

    def _default_kb(self) -> dict:
        return {
            "version": 1,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "total_learning_cycles": 0,
            "genres": {},           # genre -> accumulated knowledge
            "global_tips": [],      # Cross-genre writing tips
            "style_evolution": [],  # [{cycle, changes, reason}]
            "top_performing_elements": [],
        }

    def save(self) -> None:
        """Persist knowledge base to disk."""
        self._data["updated_at"] = datetime.utcnow().isoformat()
        with open(self.kb_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    # ── Genre Knowledge ─────────────────────────────────

    def get_genre_knowledge(self, genre: str) -> dict:
        """Get accumulated knowledge for a specific genre."""
        return self._data["genres"].get(genre, {
            "best_practices": [],
            "pitfalls": [],
            "optimal_word_count": 2000,
            "optimal_dialogue_ratio": 0.35,
            "successful_elements": [],
            "chapter_count": 0,
            "avg_quality": 0.0,
        })

    def update_genre_knowledge(self, genre: str, updates: dict) -> None:
        """Merge new knowledge into a genre's profile."""
        if genre not in self._data["genres"]:
            self._data["genres"][genre] = self.get_genre_knowledge(genre)

        gk = self._data["genres"][genre]
        for key, value in updates.items():
            if key in ("best_practices", "pitfalls", "successful_elements"):
                # Merge lists — keep unique entries, newest first
                existing = set(gk.get(key, []))
                for item in value:
                    if item not in existing:
                        gk[key].insert(0, item)
                        existing.add(item)
                # Keep top 20
                gk[key] = gk[key][:20]
            elif key in ("optimal_word_count", "optimal_dialogue_ratio", "avg_quality"):
                # Weighted average (80% old, 20% new)
                old = gk.get(key, value)
                gk[key] = round(old * 0.8 + value * 0.2, 2)
            elif key == "chapter_count":
                gk[key] = gk.get(key, 0) + value
            else:
                gk[key] = value

    # ── Global Tips ─────────────────────────────────────

    def add_global_tip(self, tip: str) -> None:
        """Add a cross-genre writing tip."""
        if tip not in self._data["global_tips"]:
            self._data["global_tips"].insert(0, tip)
            self._data["global_tips"] = self._data["global_tips"][:30]

    def get_global_tips(self, count: int = 5) -> list[str]:
        """Get top N global writing tips."""
        return self._data["global_tips"][:count]

    # ── Style Evolution ─────────────────────────────────

    def record_evolution(self, cycle_info: dict) -> None:
        """Record a style evolution step."""
        self._data["style_evolution"].append({
            "cycle": self._data["total_learning_cycles"],
            "timestamp": datetime.utcnow().isoformat(),
            **cycle_info,
        })
        # Keep last 50 evolution records
        self._data["style_evolution"] = self._data["style_evolution"][-50:]

    # ── Top Elements ────────────────────────────────────

    def update_top_elements(self, elements: list[dict]) -> None:
        """Update the top-performing element combinations."""
        self._data["top_performing_elements"] = sorted(
            elements, key=lambda x: x.get("avg_quality", 0), reverse=True
        )[:15]

    # ── Learning Context (for injection into prompts) ──

    def get_learning_context(self, genre: str) -> str:
        """Generate a short context string to inject into chapter writing prompts.

        Contains the most relevant learned knowledge for the current genre.
        """
        gk = self.get_genre_knowledge(genre)
        tips = self.get_global_tips(3)

        lines = ["[系统学习经验]"]

        if gk.get("best_practices"):
            lines.append("成功经验:")
            for bp in gk["best_practices"][:3]:
                lines.append(f"  • {bp}")

        if gk.get("pitfalls"):
            lines.append("避免问题:")
            for p in gk["pitfalls"][:2]:
                lines.append(f"  • {p}")

        if gk.get("optimal_word_count"):
            lines.append(f"最佳字数: ~{gk['optimal_word_count']}字/章")
        if gk.get("optimal_dialogue_ratio"):
            lines.append(f"最佳对话比例: ~{int(gk['optimal_dialogue_ratio'] * 100)}%")

        if tips:
            lines.append("通用技巧:")
            for t in tips:
                lines.append(f"  • {t}")

        if gk.get("successful_elements"):
            lines.append(f"高效元素: {', '.join(gk['successful_elements'][:5])}")

        return "\n".join(lines)

    # ── Stats ───────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get summary statistics."""
        genres = self._data["genres"]
        return {
            "total_cycles": self._data["total_learning_cycles"],
            "genres_tracked": len(genres),
            "total_tips": len(self._data["global_tips"]),
            "evolution_steps": len(self._data["style_evolution"]),
            "genre_summary": {
                g: {
                    "chapters": gk.get("chapter_count", 0),
                    "avg_quality": gk.get("avg_quality", 0),
                    "best_practices_count": len(gk.get("best_practices", [])),
                }
                for g, gk in genres.items()
            },
        }
