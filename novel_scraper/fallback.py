"""Alternate source and mirror resolver for novel chapters when primary fetch fails."""

import logging
import re
import urllib.parse
from typing import Optional
from bs4 import BeautifulSoup
import requests

from novel_scraper.content_extractor import ContentExtractor
from novel_scraper.models import ChapterContent, ChapterInfo

logger = logging.getLogger(__name__)

# Trusted public web novel mirror domains
MIRROR_DOMAINS = [
    "novelfull.com",
    "readnovelfull.com",
    "novelbuddy.com",
    "novelcool.com",
    "freewebnovel.com",
    "boxnovel.com",
    "allnovelupdates.com",
    "readlightnovel.me",
    "novel-bin.net",
    "wuxiabox.com",
]


class AlternateChapterFinder:
    """Finds and extracts chapter content from alternate mirrors when primary fetch fails."""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def find_alternate(
        self,
        novel_title: str,
        chapter_number: Optional[float],
        chapter_title: str,
        original_url: str,
    ) -> Optional[ChapterContent]:
        """Attempt to locate and extract chapter text from alternate sources."""
        if chapter_number is None:
            # Try to parse chapter number from title or URL
            from novel_scraper.utils import parse_chapter_number
            chapter_number = parse_chapter_number(chapter_title) or parse_chapter_number(original_url)

        if chapter_number is None:
            return None

        clean_num = int(chapter_number) if chapter_number.is_integer() else chapter_number

        # 1. Search public mirrors for novel title + chapter number
        candidate_urls = self._search_mirrors(novel_title, clean_num)
        for url in candidate_urls:
            try:
                resp = self.session.get(url, headers=self.headers, timeout=12.0)
                if resp.status_code != 200:
                    continue

                extractor = ContentExtractor(base_url=url)
                clean_html, paragraphs = extractor.clean(resp.text)

                # Validate: check reasonable length (>10 paragraphs or >300 chars)
                if len(paragraphs) >= 5 and sum(len(p) for p in paragraphs) > 300:
                    logger.info("Successfully recovered Chapter %s from alternate mirror: %s", clean_num, url)
                    info = ChapterInfo(
                        url=original_url,
                        title=chapter_title,
                        order_index=0,
                        chapter_number=chapter_number,
                    )
                    return ChapterContent(
                        chapter_info=info,
                        clean_html=clean_html,
                        paragraphs=paragraphs,
                        raw_html=resp.text,
                    )
            except Exception as e:
                logger.debug("Failed extracting alternate from %s: %e", url, e)
                continue

        # 2. Wayback Machine snapshot check
        wayback_content = self._check_wayback(original_url, chapter_title, chapter_number)
        if wayback_content:
            return wayback_content

        return None

    def _search_mirrors(self, novel_title: str, chapter_num: float | int) -> list[str]:
        """Query DuckDuckGo HTML search for candidate mirror URLs."""
        query = f'"{novel_title}" "Chapter {chapter_num}"'
        search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"

        candidate_urls: list[str] = []
        try:
            resp = self.session.get(search_url, headers=self.headers, timeout=8.0)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.select("a.result__url"):
                href = a.get("href", "").strip()
                # DuckDuckGo sometimes wraps links in uddg redirect
                if "uddg=" in href:
                    parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
                    if "uddg" in parsed:
                        href = parsed["uddg"][0]

                text_url = href if href.startswith("http") else f"https://{href}"

                # Match against known mirror domains
                if any(domain in text_url.lower() for domain in MIRROR_DOMAINS):
                    # Check that URL or link title indicates this specific chapter
                    if re.search(rf"\bchapter[-_]?{chapter_num}\b", text_url, re.IGNORECASE):
                        if text_url not in candidate_urls:
                            candidate_urls.append(text_url)

        except Exception as e:
            logger.debug("Mirror search error: %s", e)

        return candidate_urls

    def _check_wayback(
        self, original_url: str, chapter_title: str, chapter_number: Optional[float]
    ) -> Optional[ChapterContent]:
        """Check Internet Archive Wayback Machine for cached snapshots."""
        try:
            api_url = f"https://archive.org/wayback/available?url={urllib.parse.quote(original_url)}"
            resp = self.session.get(api_url, headers=self.headers, timeout=6.0)
            if resp.status_code == 200:
                data = resp.json()
                snapshots = data.get("archived_snapshots", {})
                closest = snapshots.get("closest", {})
                if closest.get("available") and closest.get("url"):
                    snapshot_url = closest["url"]
                    page_resp = self.session.get(snapshot_url, headers=self.headers, timeout=10.0)
                    if page_resp.status_code == 200:
                        extractor = ContentExtractor(base_url=original_url)
                        clean_html, paragraphs = extractor.clean(page_resp.text)
                        if len(paragraphs) >= 5:
                            info = ChapterInfo(
                                url=original_url,
                                title=chapter_title,
                                order_index=0,
                                chapter_number=chapter_number,
                            )
                            return ChapterContent(
                                chapter_info=info,
                                clean_html=clean_html,
                                paragraphs=paragraphs,
                                raw_html=page_resp.text,
                            )
        except Exception as e:
            logger.debug("Wayback Machine check error: %s", e)
        return None
