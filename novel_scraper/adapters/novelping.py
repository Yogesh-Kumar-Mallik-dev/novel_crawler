"""NovelPing website adapter."""

import re
import urllib.parse
from typing import Optional
from bs4 import BeautifulSoup
import requests

from novel_scraper.adapters.base import BaseAdapter, register_adapter
from novel_scraper.content_extractor import ContentExtractor
from novel_scraper.exceptions import (
    ChapterDiscoveryError,
    ChapterExtractionError,
    NetworkError,
)
from novel_scraper.models import ChapterContent, ChapterInfo, NovelMetadata
from novel_scraper.utils import parse_chapter_number


@register_adapter
class NovelPingAdapter(BaseAdapter):
    """Adapter for NovelPing (novelping.com)."""

    name: str = "NovelPing"
    domain: str = "novelping.com"

    @classmethod
    def can_handle(cls, url: str) -> bool:
        """Check if URL belongs to novelping.com."""
        parsed = urllib.parse.urlsplit(url.strip())
        netloc = parsed.netloc.lower()
        return "novelping.com" in netloc

    def _extract_novel_slug(self, url: str) -> str:
        """Extract novel slug from a NovelPing book or chapter URL."""
        parsed = urllib.parse.urlsplit(url.strip())
        parts = [p for p in parsed.path.split("/") if p]
        # Paths are typically: /book/<novel-slug> or /book/<novel-slug>/<chapter-slug>
        if len(parts) >= 2 and parts[0] == "book":
            return parts[1]
        raise ValueError(f"Could not extract novel slug from URL: {url}")

    def _get_novel_url(self, url: str) -> str:
        """Return the canonical book URL given any novel or chapter URL."""
        slug = self._extract_novel_slug(url)
        return f"https://novelping.com/book/{slug}"

    def get_novel_metadata(self, url: str) -> NovelMetadata:
        """Fetch and extract novel metadata."""
        book_url = self._get_novel_url(url)
        novel_slug = self._extract_novel_slug(url)

        try:
            resp = self.session.get(book_url, timeout=self.config.request_timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise NetworkError(f"Failed to fetch novel metadata from {book_url}: {e}") from e

        soup = BeautifulSoup(resp.text, "lxml")

        # Title extraction
        title = None
        og_name = soup.find("meta", property="og:novel:novel_name")
        if og_name and og_name.get("content"):
            title = og_name["content"].strip()
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"].split("|")[0].strip()
        if not title:
            h1 = soup.select_one("h1 a.novel-link") or soup.find("h1")
            if h1:
                title = h1.get_text().strip()
        if not title:
            title = novel_slug.replace("-", " ").title()

        # Author
        author = None
        author_meta = soup.find("meta", property="og:novel:author")
        if author_meta and author_meta.get("content"):
            author = author_meta["content"].strip()
        if not author:
            author_el = soup.select_one(".author a") or soup.select_one(".author")
            if author_el:
                author = author_el.get_text().strip()

        # Cover image
        cover_url = None
        cover_meta = soup.find("meta", property="og:image")
        if cover_meta and cover_meta.get("content"):
            cover_url = cover_meta["content"].strip()
        if not cover_url:
            cover_img = soup.select_one("img.novel-cover-loading") or soup.select_one(".book-cover img")
            if cover_img and cover_img.get("src"):
                cover_url = cover_img["src"]

        # Description
        description = None
        desc_meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        if desc_meta and desc_meta.get("content"):
            description = desc_meta["content"].strip()
        if not description:
            desc_el = soup.select_one(".desc-text")
            if desc_el:
                description = desc_el.get_text(separator="\n").strip()

        # Genres
        genres: list[str] = []
        genre_meta = soup.find("meta", property="og:novel:genre")
        if genre_meta and genre_meta.get("content"):
            genres = [g.strip() for g in genre_meta["content"].split(",") if g.strip()]
        if not genres:
            for g_tag in soup.select("a[href*='genres']"):
                g_text = g_tag.get_text().strip()
                if g_text and g_text not in genres:
                    genres.append(g_text)

        # Status
        status = None
        status_meta = soup.find("meta", property="og:novel:status")
        if status_meta and status_meta.get("content"):
            status = status_meta["content"].strip()
        if not status:
            status_el = soup.select_one(".text-success") or soup.select_one(".text-primary")
            if status_el:
                status = status_el.get_text().strip()

        return NovelMetadata(
            title=title,
            source_url=book_url,
            author=author,
            description=description,
            cover_url=cover_url,
            genres=genres,
            status=status,
            novel_id=novel_slug,
        )

    def discover_chapters(self, url: str) -> list[ChapterInfo]:
        """Discover all chapters for this novel in chronological order."""
        novel_slug = self._extract_novel_slug(url)
        book_url = self._get_novel_url(url)

        # 1. Primary method: Fetch AJAX chapter archive endpoint
        archive_url = f"https://novelping.com/ajax/chapter-archive?novelId={novel_slug}"
        try:
            resp = self.session.get(archive_url, timeout=self.config.request_timeout)
            if resp.status_code == 200 and resp.text.strip():
                chapters = self._parse_archive_html(resp.text, book_url)
                if chapters:
                    return chapters
        except requests.RequestException:
            # Fallback to book page if archive request fails
            pass

        # 2. Fallback: Parse book page for chapters
        try:
            resp = self.session.get(book_url, timeout=self.config.request_timeout)
            resp.raise_for_status()
            chapters = self._parse_book_page_chapters(resp.text, book_url)
            if chapters:
                return chapters
        except requests.RequestException as e:
            raise ChapterDiscoveryError(f"Failed to access novel page at {book_url}: {e}") from e

        raise ChapterDiscoveryError(f"No chapters could be discovered for {url}")

    def _parse_archive_html(self, html: str, book_url: str) -> list[ChapterInfo]:
        """Parse chapters from the NovelPing AJAX chapter-archive response."""
        soup = BeautifulSoup(html, "lxml")
        chapters: list[ChapterInfo] = []
        seen_urls: set[str] = set()

        # The archive returns a <template data-chapter-item-template> or direct list items
        # First check inside <template>
        template = soup.find("template")
        container = template if template else soup

        a_tags = container.find_all("a")
        # If no <a> tags found, try regex as a resilient fallback
        if not a_tags:
            matches = re.findall(
                r'<li[^>]*data-chapter-item[^>]*>.*?<a\s+[^>]*href=[\"\']([^\"\']+)[\"\'][^>]*title=[\"\']([^\"\']*)[\"\']',
                html,
                re.DOTALL,
            )
            for href, title in matches:
                url = urllib.parse.urljoin("https://novelping.com", href)
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                order_idx = len(chapters) + 1
                ch_num = parse_chapter_number(title)
                chapters.append(
                    ChapterInfo(
                        url=url,
                        title=title.strip(),
                        order_index=order_idx,
                        chapter_number=ch_num,
                        novel_url=book_url,
                    )
                )
            return chapters

        for a in a_tags:
            href = a.get("href")
            if not href or href == "javascript:void(0)":
                continue
            url = urllib.parse.urljoin("https://novelping.com", href)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = a.get("title") or a.get_text().strip()
            order_idx = len(chapters) + 1
            ch_num = parse_chapter_number(title)

            chapters.append(
                ChapterInfo(
                    url=url,
                    title=title.strip(),
                    order_index=order_idx,
                    chapter_number=ch_num,
                    novel_url=book_url,
                )
            )

        return chapters

    def _parse_book_page_chapters(self, html: str, book_url: str) -> list[ChapterInfo]:
        """Parse initial chapter list from the main book page."""
        soup = BeautifulSoup(html, "lxml")
        chapters: list[ChapterInfo] = []
        seen_urls: set[str] = set()

        # Check for first chapters template or #list-chapter
        template = soup.find("template", attrs={"data-first-chapter-template": True})
        container = template if template else soup.select_one("#list-chapter")

        if container:
            for a in container.find_all("a"):
                href = a.get("href")
                if not href or "chapter-" not in href:
                    continue
                url = urllib.parse.urljoin("https://novelping.com", href)
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title = a.get("title") or a.get_text().strip()
                order_idx = len(chapters) + 1
                ch_num = parse_chapter_number(title)

                chapters.append(
                    ChapterInfo(
                        url=url,
                        title=title.strip(),
                        order_index=order_idx,
                        chapter_number=ch_num,
                        novel_url=book_url,
                    )
                )

        return chapters

    def extract_chapter(self, url: str) -> ChapterContent:
        """Fetch and extract clean content for a single NovelPing chapter."""
        try:
            resp = self.session.get(url, timeout=self.config.request_timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise NetworkError(f"Failed to fetch chapter from {url}: {e}") from e

        soup = BeautifulSoup(resp.text, "lxml")

        # Title extraction
        title = None
        title_el = soup.select_one("h2 a.chr-title span.chr-text") or soup.select_one(".chr-title")
        if title_el:
            title = title_el.get_text().strip()
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                raw_title = og_title["content"].split("|")[0].strip()
                # If format is "Novel Name – Chapter X - Title", extract chapter part
                if "–" in raw_title:
                    title = raw_title.split("–", 1)[1].strip()
                elif "-" in raw_title:
                    title = raw_title.split("-", 1)[1].strip()
                else:
                    title = raw_title

        if not title:
            title = "Chapter"

        # Content extraction
        extractor = ContentExtractor(base_url="https://novelping.com")
        try:
            clean_html, paragraphs = extractor.clean(resp.text, container_selector="#chr-content")
        except ChapterExtractionError:
            # Try fallback without selector
            clean_html, paragraphs = extractor.clean(resp.text)

        chapter_info = ChapterInfo(
            url=url,
            title=title,
            order_index=0,
            chapter_number=parse_chapter_number(title),
            novel_url=self._get_novel_url(url),
        )

        return ChapterContent(
            chapter_info=chapter_info,
            clean_html=clean_html,
            paragraphs=paragraphs,
            raw_html=resp.text,
        )
