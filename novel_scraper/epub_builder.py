"""EPUB 3 generator with metadata, table of contents, and styling."""

import html
import mimetypes
from pathlib import Path
from typing import Optional
import zipfile
import ebooklib
from ebooklib import epub
import requests

from novel_scraper.config import Config
from novel_scraper.exceptions import EpubGenerationError
from novel_scraper.models import ChapterRecord, NovelMetadata
from novel_scraper.utils import create_session, sanitize_filename

DEFAULT_CSS = """
@namespace epub "http://www.idpf.org/2007/ops";

body {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1.05em;
    line-height: 1.6;
    margin: 1.5em;
    color: #1a1a1a;
}

h1, h2, h3 {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    text-align: center;
    font-weight: 600;
    margin-top: 1.5em;
    margin-bottom: 1em;
}

h2 {
    font-size: 1.4em;
    border-bottom: 1px solid #eaeaea;
    padding-bottom: 0.3em;
}

p {
    margin-top: 0;
    margin-bottom: 0.8em;
    text-indent: 1.5em;
    text-align: justify;
}

p:first-of-type {
    text-indent: 0;
}

img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 1em auto;
}

hr {
    border: 0;
    height: 1px;
    background: #ccc;
    margin: 2em 0;
}

.chapter-content {
    margin-top: 1.5em;
}
"""


class EpubBuilder:
    """Builds valid EPUB 3 archives from downloaded novel chapters."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.session = create_session(self.config)

    def build_epub(
        self,
        metadata: NovelMetadata,
        chapters: list[ChapterRecord],
        output_path: Optional[Path] = None,
    ) -> Path:
        """Create an EPUB 3 file from metadata and chapter records.

        Args:
            metadata: Novel metadata object.
            chapters: List of downloaded chapters (must contain content_html).
            output_path: Target .epub file path. If None, default is used.

        Returns:
            The Path to the generated EPUB file.
        """
        if not chapters:
            raise EpubGenerationError("Cannot generate EPUB with zero chapters.")

        # Determine target output path
        if not output_path:
            download_dir = Path(self.config.download_dir)
            download_dir.mkdir(parents=True, exist_ok=True)
            safe_title = sanitize_filename(metadata.title)
            output_path = download_dir / f"{safe_title}.epub"
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

        book = epub.EpubBook()

        # 1. Dublin Core Metadata
        novel_identifier = metadata.novel_id or sanitize_filename(metadata.title)
        book.set_identifier(f"novel-scraper-{novel_identifier}")
        book.set_title(metadata.title)
        book.set_language("en")

        if metadata.author:
            book.add_author(metadata.author)

        if metadata.description:
            book.add_metadata("DC", "description", metadata.description)

        if metadata.source_url:
            book.add_metadata("DC", "source", metadata.source_url)

        # 2. Add Stylesheet
        css_item = epub.EpubItem(
            uid="style_default",
            file_name="style/style.css",
            media_type="text/css",
            content=DEFAULT_CSS.encode("utf-8"),
        )
        book.add_item(css_item)

        # 3. Add Cover Image if available
        if metadata.cover_url:
            self._add_cover(book, metadata.cover_url)

        # 4. Add Chapters
        epub_chapters: list[epub.EpubHtml] = []
        for ch in chapters:
            content_body = (
                ch.content_html
                or f'<p><em>{html.escape(ch.title)} - Content not yet downloaded (<a href="{html.escape(ch.url)}">Web Source</a>).</em></p>'
            )
            escaped_title = html.escape(ch.title)

            chapter_item = epub.EpubHtml(
                title=ch.title,
                file_name=f"chapter_{ch.order_index:05d}.xhtml",
                lang="en",
            )
            chapter_item.content = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<!DOCTYPE html>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml" '
                'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en">\n'
                '<head>\n'
                f"    <title>{escaped_title}</title>\n"
                '    <link rel="stylesheet" type="text/css" href="style/style.css" />\n'
                "</head>\n"
                "<body>\n"
                f"    <h2>{escaped_title}</h2>\n"
                '    <div class="chapter-content">\n'
                f"        {content_body}\n"
                "    </div>\n"
                "</body>\n"
                "</html>"
            )
            chapter_item.add_item(css_item)
            book.add_item(chapter_item)
            epub_chapters.append(chapter_item)

        # 5. Table of contents, NCX, Navigation
        book.toc = tuple(epub_chapters)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        # 6. Spine
        book.spine = ["nav"] + epub_chapters

        # 7. Write EPUB file
        try:
            epub.write_epub(str(output_path), book, {})
        except Exception as exc:
            raise EpubGenerationError(f"Failed to write EPUB file to {output_path}: {exc}") from exc

        # 8. Validate generated EPUB
        self._validate_epub(output_path)
        return output_path

    def _add_cover(self, book: epub.EpubBook, cover_url: str) -> None:
        """Fetch and attach cover image to EPUB."""
        try:
            resp = self.session.get(cover_url, timeout=10.0)
            if resp.status_code == 200 and resp.content:
                ext = ".jpg"
                if "png" in cover_url.lower():
                    ext = ".png"
                elif "webp" in cover_url.lower():
                    ext = ".webp"
                book.set_cover(f"cover{ext}", resp.content, create_page=True)
        except Exception:
            # Non-fatal: continue without cover if fetching fails
            pass

    def _validate_epub(self, path: Path) -> None:
        """Validate that the EPUB file exists, is non-empty, and contains valid zip structures."""
        if not path.is_file():
            raise EpubGenerationError(f"EPUB file was not created: {path}")

        if path.stat().st_size == 0:
            raise EpubGenerationError(f"Generated EPUB file is empty (0 bytes): {path}")

        try:
            with zipfile.ZipFile(path, "r") as zf:
                namelist = zf.namelist()
                if "mimetype" not in namelist:
                    raise EpubGenerationError("Invalid EPUB: missing 'mimetype' entry.")
                if not any("container.xml" in name for name in namelist):
                    raise EpubGenerationError("Invalid EPUB: missing META-INF/container.xml.")
        except zipfile.BadZipFile as e:
            raise EpubGenerationError(f"Corrupted EPUB zip archive: {e}") from e
