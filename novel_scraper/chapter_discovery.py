"""Chapter discovery and filtering logic."""

from typing import Optional

from novel_scraper.adapters.base import BaseAdapter, get_adapter
from novel_scraper.config import Config
from novel_scraper.exceptions import ChapterDiscoveryError
from novel_scraper.models import ChapterInfo


class ChapterDiscoverer:
    """Discovers and filters chapters for a given novel URL."""

    def __init__(self, adapter: Optional[BaseAdapter] = None, config: Optional[Config] = None):
        self.adapter = adapter
        self.config = config or Config()

    def discover(self, url: str) -> list[ChapterInfo]:
        """Discover all available chapters from the URL using the appropriate adapter."""
        adapter = self.adapter or get_adapter(url, config=self.config)
        chapters = adapter.discover_chapters(url)
        if not chapters:
            raise ChapterDiscoveryError(f"No chapters found for URL: {url}")
        return chapters

    @staticmethod
    def filter_chapters(
        chapters: list[ChapterInfo],
        start_chapter: Optional[float] = None,
        end_chapter: Optional[float] = None,
    ) -> list[ChapterInfo]:
        """Filter a list of chapters by chapter numbers or order index.

        If chapter_number is available, filters using chapter_number.
        If a chapter has no numeric number (e.g. Prologue), filters using its 1-based order_index.
        """
        if start_chapter is None and end_chapter is None:
            return list(chapters)

        filtered: list[ChapterInfo] = []

        for ch in chapters:
            # Determine the comparison value: prefer ch.chapter_number, fallback to ch.order_index
            val = ch.chapter_number if ch.chapter_number is not None else float(ch.order_index)

            if start_chapter is not None and val < start_chapter:
                continue
            if end_chapter is not None and val > end_chapter:
                continue
            filtered.append(ch)

        return filtered
