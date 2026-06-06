"""Local file output management for generated novels."""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.utils.text_utils import sanitize_filename

logger = logging.getLogger(__name__)


class FileStore:
    """Manages file output for novels and chapters."""

    def __init__(self, output_dir: str | Path = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_novel_dir(self, novel_title: str) -> Path:
        """Get (and create) the output directory for a specific novel."""
        safe_title = sanitize_filename(novel_title)
        novel_dir = self.output_dir / safe_title
        novel_dir.mkdir(parents=True, exist_ok=True)
        return novel_dir

    def save_chapter(
        self,
        novel_title: str,
        chapter_number: int,
        chapter_title: str,
        content: str,
    ) -> Path:
        """Save a chapter as a txt file.

        Args:
            novel_title: Name of the novel.
            chapter_number: Chapter number.
            chapter_title: Title of the chapter.
            content: Chapter content text.

        Returns:
            Path to the saved file.
        """
        novel_dir = self.get_novel_dir(novel_title)
        filename = f"chapter_{chapter_number:04d}.txt"
        filepath = novel_dir / filename

        # Format chapter with header
        header = f"第{chapter_number}章 {chapter_title}\n\n"
        full_content = header + content + "\n"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(full_content)

        logger.info("Saved chapter: %s (%d chars)", filepath, len(content))
        return filepath

    def save_story_bible(self, novel_title: str, story_bible: dict) -> Path:
        """Save the story bible as JSON."""
        novel_dir = self.get_novel_dir(novel_title)
        filepath = novel_dir / "story_bible.json"

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(story_bible, f, ensure_ascii=False, indent=2, default=str)

        logger.debug("Saved story bible: %s", filepath)
        return filepath

    def load_story_bible(self, novel_title: str) -> dict | None:
        """Load the story bible from JSON."""
        novel_dir = self.get_novel_dir(novel_title)
        filepath = novel_dir / "story_bible.json"

        if not filepath.exists():
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_metadata(self, novel_title: str, metadata: dict) -> Path:
        """Save novel metadata as JSON."""
        novel_dir = self.get_novel_dir(novel_title)
        filepath = novel_dir / "metadata.json"

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2, default=str)

        return filepath

    def save_full_novel(self, novel_title: str, chapters: list[dict]) -> Path:
        """Compile all chapters into a single txt file."""
        novel_dir = self.get_novel_dir(novel_title)
        safe_title = sanitize_filename(novel_title)
        filepath = novel_dir / f"{safe_title}_全文.txt"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"《{novel_title}》\n")
            f.write(f"生成时间：{datetime.now().isoformat()}\n")
            f.write("=" * 60 + "\n\n")

            for ch in sorted(chapters, key=lambda c: c["number"]):
                f.write(f"第{ch['number']}章 {ch['title']}\n\n")
                f.write(ch["content"] + "\n\n")
                f.write("-" * 40 + "\n\n")

        logger.info("Saved full novel: %s", filepath)
        return filepath

    def list_novels(self) -> list[str]:
        """List all novel titles in the output directory."""
        if not self.output_dir.exists():
            return []
        return [
            d.name for d in self.output_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
