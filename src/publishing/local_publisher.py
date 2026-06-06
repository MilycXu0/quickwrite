"""Local Publisher — outputs novels to local files in various formats."""

import logging
from datetime import datetime
from pathlib import Path

from src.publishing.format_epub import EpubFormatter
from src.storage.file_store import FileStore

logger = logging.getLogger(__name__)


class LocalPublisher:
    """Publishes novel chapters to local files.

    Supports TXT and EPUB formats. Extensible for future platform adapters.
    """

    def __init__(self, file_store: FileStore):
        self.files = file_store
        self._epub_formatter = EpubFormatter()

    def publish_chapter(
        self,
        novel_title: str,
        chapter_number: int,
        chapter_title: str,
        content: str,
        format: str = "txt",
    ) -> Path:
        """Publish a single chapter.

        Args:
            novel_title: Name of the novel.
            chapter_number: Chapter number.
            chapter_title: Chapter title.
            content: Chapter content text.
            format: Output format ("txt" or "epub").

        Returns:
            Path to the published file.
        """
        if format in ("txt", "epub"):
            return self.files.save_chapter(novel_title, chapter_number, chapter_title, content)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def publish_novel_metadata(
        self,
        novel_title: str,
        metadata: dict,
    ) -> Path:
        """Publish novel metadata file."""
        return self.files.save_metadata(novel_title, metadata)

    def compile_novel_txt(
        self,
        novel_title: str,
        chapters: list[dict],
    ) -> Path:
        """Compile all chapters into a single TXT file.

        Args:
            novel_title: Name of the novel.
            chapters: List of {number, title, content} dicts, sorted by chapter number.

        Returns:
            Path to the compiled file.
        """
        return self.files.save_full_novel(novel_title, chapters)

    def compile_novel_epub(
        self,
        novel_title: str,
        author: str,
        chapters: list[dict],
        genre: str = "",
        synopsis: str = "",
    ) -> Path:
        """Compile all chapters into a single EPUB file.

        Args:
            novel_title: Name of the novel.
            author: Author name.
            chapters: List of {number, title, content} dicts.
            genre: Genre tag for metadata.
            synopsis: Book synopsis.

        Returns:
            Path to the EPUB file.
        """
        novel_dir = self.files.get_novel_dir(novel_title)
        epub_path = novel_dir / f"{novel_title}.epub"

        return self._epub_formatter.create_epub(
            title=novel_title,
            author=author,
            chapters=chapters,
            output_path=epub_path,
            genre=genre,
            synopsis=synopsis,
        )

    def get_novel_info(self, novel_title: str) -> dict:
        """Get information about a published novel."""
        novel_dir = self.files.get_novel_dir(novel_title)
        chapters = sorted(novel_dir.glob("chapter_*.txt"))
        epub_file = novel_dir / f"{novel_title}.epub"
        return {
            "title": novel_title,
            "chapter_count": len(chapters),
            "output_dir": str(novel_dir),
            "has_metadata": (novel_dir / "metadata.json").exists(),
            "has_bible": (novel_dir / "story_bible.json").exists(),
            "has_epub": epub_file.exists(),
        }
