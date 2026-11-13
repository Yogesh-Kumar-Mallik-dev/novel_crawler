"""Generic website adapter for scraping novels directly from any HTTP/HTTPS URL."""

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
from novel_scraper.utils import parse_chapter_number, sanitize_filename


@register_adapter
class GenericAdapter(BaseAdapter):
    """Fallback adapter capable of scraping chapters directly from any public web novel URL."""

    name: str = "Generic Direct-URL Scraper"
    domain: str = "* (Any standard novel website)"
    is_generic: bool = True

    @classmethod
    def can_handle(cls, url: str) -> bool:
        """Handle any valid HTTP/HTTPS URL as a universal fallback."""
        parsed = urllib.parse.urlsplit(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)

    def get_novel_metadata(self, url: str) -> NovelMetadata:
        """Extract metadata heuristics from HTML headers and OpenGraph tags."""
        try:
            resp = self.session.get(url, timeout=self.config.request_timeout)
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException as e:
            raise NetworkError(f"Failed to fetch metadata from {url}: {e}") from e

        return self.parse_metadata_from_html(html, url)

    def parse_metadata_from_html(self, html: str, url: str) -> NovelMetadata:
        """Parse novel metadata from raw HTML."""
        soup = BeautifulSoup(html, "lxml")

        # 1. Title
        title = None
        for prop in ["og:novel:novel_name", "og:title", "twitter:title"]:
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                title = tag["content"].strip()
                break

        if not title and soup.title and soup.title.string:
            title = soup.title.string.strip()

        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text().strip()

        if title:
            # Clean common trailing site names like " - Read Online", " | NovelSite"
            title = re.split(r"\s+[|\-–—:]\s+(?:Read\s+Online|Chapter|Novel)", title, flags=re.IGNORECASE)[0].strip()
        else:
            title = "Web Novel"

        # 2. Author
        author = None
        for prop in ["og:novel:author", "author", "article:author"]:
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                author = tag["content"].strip()
                break

        if not author:
            author_tag = soup.select_one(".author a") or soup.select_one(".author")
            if author_tag:
                author = author_tag.get_text().strip()

        # 3. Cover image
        cover_url = None
        cover_tag = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
        if cover_tag and cover_tag.get("content"):
            cover_url = urllib.parse.urljoin(url, cover_tag["content"].strip())

        # 4. Description
        description = None
        desc_tag = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if desc_tag and desc_tag.get("content"):
            description = desc_tag["content"].strip()

        # Slug / ID
        parsed = urllib.parse.urlsplit(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        novel_id = path_parts[0] if path_parts else sanitize_filename(title)

        return NovelMetadata(
            title=title,
            source_url=url,
            author=author,
            description=description,
            cover_url=cover_url,
            novel_id=novel_id,
        )

    def discover_chapters(self, url: str) -> list[ChapterInfo]:
        """Discover chapters via chapter index links on page or direct chapter navigation."""
        try:
            resp = self.session.get(url, timeout=self.config.request_timeout)
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException as e:
            raise ChapterDiscoveryError(f"Failed to fetch {url} for discovery: {e}") from e

        return self.parse_chapters_from_html(html, url)

    def parse_chapters_from_html(self, html: str, url: str) -> list[ChapterInfo]:
        """Parse chapter list or single chapter from HTML."""
        soup = BeautifulSoup(html, "lxml")
        chapters: list[ChapterInfo] = []
        seen_urls: set[str] = set()

        # 1. Search for links likely to be chapters
        candidate_links = soup.find_all("a", href=True)
        chapter_candidates: list[tuple[str, str]] = []

        for a in candidate_links:
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue

            full_url = urllib.parse.urljoin(url, href)
            full_url = urllib.parse.urldefrag(full_url)[0]

            title = (a.get("title") or a.get_text()).strip()
            if not title:
                continue

            is_ch_url = bool(re.search(r"/(?:chapter|ch|chap|c)[-_]?\d+", full_url, re.IGNORECASE))
            is_ch_title = bool(re.search(r"\b(?:chapter|ch\.?|episode)\s*\d+", title, re.IGNORECASE))

            if is_ch_url or is_ch_title:
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    chapter_candidates.append((full_url, title))

        if chapter_candidates:
            for idx, (ch_url, ch_title) in enumerate(chapter_candidates, start=1):
                chapters.append(
                    ChapterInfo(
                        url=ch_url,
                        title=ch_title,
                        order_index=idx,
                        chapter_number=parse_chapter_number(ch_title),
                        novel_url=url,
                    )
                )
            return chapters

        # 2. If no chapter list was detected, treat current URL as a starting chapter
        ch_title = self._detect_chapter_title(soup) or "Chapter 1"
        ch_num = parse_chapter_number(ch_title) or 1.0

        chapters.append(
            ChapterInfo(
                url=url,
                title=ch_title,
                order_index=1,
                chapter_number=ch_num,
                novel_url=url,
            )
        )
        return chapters

    def extract_chapter(self, url: str) -> ChapterContent:
        """Extract clean readable content for a single chapter directly from URL."""
        try:
            resp = self.session.get(url, timeout=self.config.request_timeout)
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException as e:
            raise NetworkError(f"Failed to fetch chapter from {url}: {e}") from e

        soup = BeautifulSoup(html, "lxml")
        title = self._detect_chapter_title(soup) or "Chapter"

        extractor = ContentExtractor(base_url=url)
        clean_html, paragraphs = extractor.clean(html)

        chapter_info = ChapterInfo(
            url=url,
            title=title,
            order_index=0,
            chapter_number=parse_chapter_number(title),
            novel_url=url,
        )

        return ChapterContent(
            chapter_info=chapter_info,
            clean_html=clean_html,
            paragraphs=paragraphs,
            raw_html=html,
        )

    def _detect_chapter_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Detect chapter title from common heading patterns."""
        for selector in ["h1.chapter-title", "h1", "h2.chapter-title", "h2", ".chr-title"]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text().strip()
                if text and len(text) < 200:
                    return text

        if soup.title and soup.title.string:
            return soup.title.string.strip()
        return None
