"""Story Bible — the canonical source of truth for novel continuity.

This module maintains the authoritative state of a novel across all chapters.
It is the single source of truth for characters, plot threads, world state,
and timeline. Every chapter generation reads from and writes to the Story Bible.
"""

import copy
import json
import logging
from datetime import datetime
from typing import Optional

from src.core.models import CharacterState, StoryBible

logger = logging.getLogger(__name__)


class StoryBibleManager:
    """Manages the Story Bible lifecycle for a novel.

    Responsibilities:
    - Create and initialize a new Story Bible for a novel
    - Load/save from persistent storage
    - Update character states after each chapter
    - Track plot threads (add, resolve, update)
    - Maintain timeline of major events
    - Manage chapter summaries
    - Export context for LLM prompts
    """

    MAX_TIMELINE_EVENTS = 200
    MAX_PLOT_THREADS = 50

    def __init__(self, novel_id: int, novel_title: str = ""):
        self.bible = StoryBible(
            novel_id=novel_id,
            novel_title=novel_title,
        )

    # ── Initialization ──────────────────────────────────

    def initialize_world(self, world_setting: dict) -> None:
        """Set the world setting from world-building generation."""
        self.bible.world_setting = world_setting
        logger.info("Story Bible: world setting initialized")

    def initialize_characters(self, characters_data: dict) -> None:
        """Initialize characters from character design generation.

        Args:
            characters_data: Output from Character Designer (protagonist + supporting + antagonists).
        """
        def _to_list(value):
            """Normalize a value to a list — handles both string and list inputs from LLM."""
            if value is None:
                return []
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                return [value] if value.strip() else []
            return [str(value)]

        # Protagonist
        protag = characters_data.get("protagonist", {})
        if protag:
            name = protag.get("name", "主角")
            self.bible.characters[name] = CharacterState(
                current_location=protag.get("starting_location", ""),
                power_level=protag.get("starting_power", "凡人"),
                active_goals=_to_list(protag.get("motivation", "")),
                notes=f"角色: {protag.get('role', 'protagonist')}",
            )

        # Supporting characters
        for char in characters_data.get("supporting_characters", []):
            name = char.get("name", "")
            if name:
                self.bible.characters[name] = CharacterState(
                    current_location="",
                    power_level="",
                    active_goals=_to_list(char.get("goals", [])),
                    notes=f"角色: {char.get('role', 'supporting')} | 关系: {char.get('relationship_to_mc', '')}",
                )

        # Antagonists
        for char in characters_data.get("antagonists", []):
            name = char.get("name", "")
            if name:
                self.bible.characters[name] = CharacterState(
                    current_location="",
                    power_level=char.get("strength", ""),
                    active_goals=_to_list(char.get("motivation", "")),
                    notes=f"角色: antagonist | 弧光: {char.get('arc', '')}",
                )

        logger.info("Story Bible: %d characters initialized", len(self.bible.characters))

    # ── Character Management ────────────────────────────

    def get_character(self, name: str) -> Optional[CharacterState]:
        """Get a character's current state."""
        return self.bible.characters.get(name)

    def update_character(self, name: str, **updates) -> None:
        """Update fields on a character's state.

        Example:
            update_character("主角", current_location="青云宗", power_level="筑基期")
        """
        char = self.bible.characters.get(name)
        if char:
            for key, value in updates.items():
                if hasattr(char, key):
                    setattr(char, key, value)
            logger.debug("Updated character '%s': %s", name, list(updates.keys()))
        else:
            logger.warning("Character '%s' not found in Story Bible", name)

    def add_character(self, name: str, state: CharacterState) -> None:
        """Add a new character introduced mid-story."""
        self.bible.characters[name] = state
        logger.info("New character added: '%s'", name)

    def get_character_names(self) -> list[str]:
        """Get all character names."""
        return list(self.bible.characters.keys())

    def get_protagonist(self) -> Optional[tuple[str, CharacterState]]:
        """Find the protagonist (heuristic: first character added)."""
        if self.bible.characters:
            first = next(iter(self.bible.characters.items()))
            return first
        return None

    # ── Plot Thread Management ──────────────────────────

    def add_plot_thread(self, thread_id: str, description: str, introduced_chapter: int) -> None:
        """Start a new plot thread."""
        if len(self.bible.active_plot_threads) >= self.MAX_PLOT_THREADS:
            # Archive oldest non-active thread
            self._archive_old_threads()

        self.bible.active_plot_threads.append({
            "id": thread_id,
            "description": description,
            "chapter_introduced": introduced_chapter,
            "chapter_resolved": None,
            "status": "active",
        })
        logger.debug("Plot thread added: %s", thread_id)

    def resolve_plot_thread(self, thread_id: str, resolved_chapter: int) -> bool:
        """Mark a plot thread as resolved."""
        for thread in self.bible.active_plot_threads:
            if thread["id"] == thread_id and thread["status"] == "active":
                thread["status"] = "resolved"
                thread["chapter_resolved"] = resolved_chapter
                logger.info("Plot thread resolved: %s at chapter %d", thread_id, resolved_chapter)
                return True
        return False

    def update_plot_thread(self, thread_id: str, description: str) -> bool:
        """Update the description of an active plot thread."""
        for thread in self.bible.active_plot_threads:
            if thread["id"] == thread_id:
                thread["description"] = description
                return True
        return False

    def get_active_plot_threads(self) -> list[dict]:
        """Get all unresolved plot threads."""
        return [t for t in self.bible.active_plot_threads if t["status"] == "active"]

    def _archive_old_threads(self) -> None:
        """Remove resolved threads older than 50 chapters from active list."""
        current_ch = self.bible.last_updated_chapter
        self.bible.active_plot_threads = [
            t for t in self.bible.active_plot_threads
            if t["status"] == "active"
            or (t.get("chapter_resolved", 0) or 0) > current_ch - 50
        ]

    # ── Timeline Management ─────────────────────────────

    def add_event(self, chapter_number: int, event: str) -> None:
        """Record a major event in the timeline."""
        self.bible.timeline.append({
            "chapter": chapter_number,
            "event": event,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # Trim old events if too many
        if len(self.bible.timeline) > self.MAX_TIMELINE_EVENTS:
            self.bible.timeline = self.bible.timeline[-self.MAX_TIMELINE_EVENTS:]

    # ── Secret/Foreshadowing Management ─────────────────

    def add_secret(self, secret_id: str, description: str, revealed_chapter: Optional[int] = None) -> None:
        """Record a secret or foreshadowing element."""
        self.bible.revealed_secrets.append({
            "id": secret_id,
            "description": description,
            "revealed_chapter": revealed_chapter,
            "status": "revealed" if revealed_chapter else "hidden",
        })

    def reveal_secret(self, secret_id: str, chapter_number: int) -> bool:
        """Mark a hidden secret as revealed."""
        for secret in self.bible.revealed_secrets:
            if secret["id"] == secret_id and secret["status"] == "hidden":
                secret["status"] = "revealed"
                secret["revealed_chapter"] = chapter_number
                return True
        return False

    # ── Chapter Summary Management ──────────────────────

    def add_chapter_summary(self, chapter_number: int, summary: str) -> None:
        """Add or update a chapter summary."""
        self.bible.chapter_summaries[chapter_number] = summary

        # Keep only the most recent 100 summaries
        if len(self.bible.chapter_summaries) > 100:
            oldest = min(self.bible.chapter_summaries.keys())
            del self.bible.chapter_summaries[oldest]

    def get_recent_summaries(self, count: int = 10) -> str:
        """Get the most recent chapter summaries formatted for LLM context."""
        sorted_chapters = sorted(self.bible.chapter_summaries.items(), reverse=True)
        recent = sorted_chapters[:count]
        lines = []
        for ch_num, summary in sorted(recent, key=lambda x: x[0]):
            lines.append(f"第{ch_num}章: {summary}")
        return "\n".join(lines)

    def post_chapter_update(self, chapter_number: int) -> None:
        """Mark that the Story Bible has been updated post-chapter."""
        self.bible.last_updated_chapter = chapter_number
        self.bible.version += 1

    # ── Context Export ──────────────────────────────────

    def get_world_context(self) -> str:
        """Format world setting for LLM context."""
        if not self.bible.world_setting:
            return "（世界观尚未设定）"
        return json.dumps(self.bible.world_setting, ensure_ascii=False, indent=2)

    def get_character_context(self) -> str:
        """Format character states for LLM context."""
        if not self.bible.characters:
            return "（暂无角色）"

        lines = []
        for name, state in self.bible.characters.items():
            lines.append(f"【{name}】")
            if state.current_location:
                lines.append(f"  位置: {state.current_location}")
            if state.power_level:
                lines.append(f"  实力: {state.power_level}")
            if state.active_goals:
                lines.append(f"  目标: {', '.join(state.active_goals)}")
            if state.inventory:
                lines.append(f"  物品: {', '.join(state.inventory)}")
            if state.notes:
                lines.append(f"  备注: {state.notes}")
        return "\n".join(lines)

    def get_plot_context(self) -> str:
        """Format active plot threads for LLM context."""
        active = self.get_active_plot_threads()
        if not active:
            return "（无进行中的情节线）"

        lines = []
        for t in active:
            lines.append(f"- [{t['id']}] (自第{t['chapter_introduced']}章) {t['description']}")
        return "\n".join(lines)

    def get_timeline_context(self, last_n: int = 30) -> str:
        """Format recent timeline events for LLM context."""
        events = self.bible.timeline[-last_n:]
        if not events:
            return "（时间线为空）"

        lines = []
        for e in events:
            lines.append(f"第{e['chapter']}章: {e['event']}")
        return "\n".join(lines)

    def get_full_context(self) -> dict:
        """Get all context components for a chapter generation call."""
        return {
            "world_setting": self.get_world_context(),
            "character_states": self.get_character_context(),
            "active_plot_threads": self.get_plot_context(),
            "timeline": self.get_timeline_context(),
        }

    # ── Persistence ─────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return self.bible.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "StoryBibleManager":
        """Deserialize from dictionary."""
        bible = StoryBible(**data)
        manager = cls(novel_id=bible.novel_id, novel_title=bible.novel_title)
        manager.bible = bible
        return manager

    def snapshot(self) -> dict:
        """Create a deep copy snapshot of the current bible state."""
        return copy.deepcopy(self.bible.model_dump())
