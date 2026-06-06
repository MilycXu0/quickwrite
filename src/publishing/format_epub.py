"""EPUB formatter — generates properly formatted EPUB ebooks.

Creates EPUB 3.0 files with:
- Metadata (title, author, genre, creation date)
- Table of contents (NCX + Nav)
- Chapter-by-chapter content with CSS styling
- Cover page (text-based)
- Proper Chinese font handling
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ebooklib import epub

from src.utils.text_utils import sanitize_filename

logger = logging.getLogger(__name__)


class EpubFormatter:
    """Generates EPUB files from novel chapters."""

    # CSS for Chinese web novel reading
    DEFAULT_CSS = """
    @namespace epub "http://www.idpf.org/2007/ops";

    body {
        font-family: "Songti SC", "SimSun", "Noto Serif CJK SC", serif;
        line-height: 1.8;
        margin: 2em;
        color: #333;
    }

    h1 {
        text-align: center;
        font-size: 1.8em;
        margin: 2em 0 1em 0;
        color: #222;
    }

    h2 {
        text-align: center;
        font-size: 1.4em;
        margin: 1.5em 0 1em 0;
        color: #444;
    }

    p {
        text-indent: 2em;
        margin: 0.5em 0;
    }

    .chapter-title {
        text-align: center;
        font-size: 1.5em;
        font-weight: bold;
        margin: 2em 0 1.5em 0;
        page-break-before: always;
    }

    .chapter-content {
        margin: 1em 0;
    }

    .metadata-page {
        text-align: center;
        margin-top: 30%;
    }

    .metadata-page h1 {
        font-size: 2em;
        margin-bottom: 0.5em;
    }

    .metadata-page .author {
        font-size: 1.2em;
        color: #666;
        margin: 1em 0;
    }

    .metadata-page .info {
        font-size: 1em;
        color: #888;
        margin: 0.5em 0;
    }
    """

    def __init__(self):
        pass

    def create_epub(
        self,
        title: str,
        author: str,
        chapters: list[dict],
        output_path: Path,
        genre: str = "",
        synopsis: str = "",
        cover_text: Optional[str] = None,
        language: str = "zh-CN",
    ) -> Path:
        """Create an EPUB file from chapters.

        Args:
            title: Novel title.
            author: Author name.
            chapters: List of {number, title, content} dicts, sorted by chapter number.
            output_path: Path to save the EPUB file.
            genre: Genre tag.
            synopsis: Book synopsis.
            cover_text: Custom cover text.
            language: Language code.

        Returns:
            Path to the created EPUB file.
        """
        book = epub.EpubBook()

        # ── Metadata ─────────────────────────────────
        book.set_identifier(f"novel-writer-{sanitize_filename(title)}-{datetime.utcnow().timestamp()}")
        book.set_title(title)
        book.set_language(language)
        book.add_author(author)
        if genre:
            book.add_metadata("DC", "subject", genre)
        book.add_metadata("DC", "date", datetime.utcnow().isoformat())
        book.add_metadata("DC", "description", synopsis[:500] if synopsis else "")

        # ── CSS ───────────────────────────────────────
        css = epub.EpubItem(
            uid="style",
            file_name="style/default.css",
            media_type="text/css",
            content=self.DEFAULT_CSS.encode("utf-8"),
        )
        book.add_item(css)

        # ── Cover page ────────────────────────────────
        cover_content = self._build_cover_html(title, author, genre, synopsis, cover_text)
        cover_page = epub.EpubHtml(
            title="封面",
            file_name="cover.xhtml",
            lang=language,
        )
        cover_page.content = cover_content.encode("utf-8")
        cover_page.add_item(css)
        book.add_item(cover_page)

        # ── Table of Contents ─────────────────────────
        toc_content = self._build_toc_html(title, chapters)
        toc_page = epub.EpubHtml(
            title="目录",
            file_name="toc.xhtml",
            lang=language,
        )
        toc_page.content = toc_content.encode("utf-8")
        toc_page.add_item(css)
        book.add_item(toc_page)

        # ── Chapter pages ─────────────────────────────
        epub_chapters = []
        spine = ["nav", cover_page, toc_page]

        for ch in sorted(chapters, key=lambda c: c["number"]):
            ch_html = self._build_chapter_html(
                ch["number"],
                ch["title"],
                ch["content"],
            )
            ch_file = epub.EpubHtml(
                title=f"第{ch['number']}章 {ch['title']}",
                file_name=f"chapter_{ch['number']:04d}.xhtml",
                lang=language,
            )
            ch_file.content = ch_html.encode("utf-8")
            ch_file.add_item(css)
            book.add_item(ch_file)

            epub_chapters.append(ch_file)
            spine.append(ch_file)

        # ── Navigation ────────────────────────────────
        book.toc = [
            epub.Link("cover.xhtml", "封面", "cover"),
            epub.Link("toc.xhtml", "目录", "toc"),
            (
                epub.Section("正文"),
                [epub.Link(f"chapter_{ch['number']:04d}.xhtml",
                           f"第{ch['number']}章 {ch['title']}",
                           f"ch{ch['number']}")
                 for ch in sorted(chapters, key=lambda c: c["number"])],
            ),
        ]

        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        # ── Spine ─────────────────────────────────────
        book.spine = spine

        # ── Write ─────────────────────────────────────
        output_path.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(output_path), book)

        logger.info("EPUB created: %s (%d chapters, %d bytes)",
                     output_path, len(chapters), output_path.stat().st_size)
        return output_path

    def _build_cover_html(
        self,
        title: str,
        author: str,
        genre: str,
        synopsis: str,
        cover_text: Optional[str] = None,
    ) -> str:
        """Build the cover page HTML."""
        genre_line = f'<p class="info">类型：{genre}</p>' if genre else ""
        synopsis_line = f'<p class="info">{synopsis[:200]}</p>' if synopsis else ""
        cover = cover_text or "AI 智能小说创作"

        return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
    <title>封面</title>
    <link rel="stylesheet" type="text/css" href="style/default.css"/>
</head>
<body>
    <div class="metadata-page">
        <h1>{title}</h1>
        <p class="author">作者：{author}</p>
        {genre_line}
        {synopsis_line}
        <p class="info">生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        <p class="info">{cover}</p>
    </div>
</body>
</html>"""

    def _build_toc_html(self, title: str, chapters: list[dict]) -> str:
        """Build the table of contents page."""
        items = []
        for ch in sorted(chapters, key=lambda c: c["number"]):
            items.append(
                f'<li><a href="chapter_{ch["number"]:04d}.xhtml">'
                f'第{ch["number"]}章 {ch["title"]}</a></li>'
            )

        return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
    <title>目录</title>
    <link rel="stylesheet" type="text/css" href="style/default.css"/>
</head>
<body>
    <h1>《{title}》— 目录</h1>
    <p>共 {len(chapters)} 章</p>
    <ol>
        {"".join(items)}
    </ol>
</body>
</html>"""

    def _build_chapter_html(self, number: int, title: str, content: str) -> str:
        """Build a single chapter's HTML."""
        # Escape HTML entities in content
        content = (
            content.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

        # Convert newlines to paragraphs
        paragraphs = []
        for line in content.split("\n"):
            line = line.strip()
            if line:
                paragraphs.append(f"<p>{line}</p>")

        return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
    <title>第{number}章 {title}</title>
    <link rel="stylesheet" type="text/css" href="style/default.css"/>
</head>
<body>
    <h2 class="chapter-title">第{number}章 {title}</h2>
    <div class="chapter-content">
        {"".join(paragraphs)}
    </div>
</body>
</html>"""
