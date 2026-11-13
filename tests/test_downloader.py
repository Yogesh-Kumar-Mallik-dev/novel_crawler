"""Tests for Downloader engine, resume logic, retry, and fault tolerance."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from novel_scraper.adapters.base import BaseAdapter
from novel_scraper.config import Config
from novel_scraper.database import Database
from novel_scraper.downloader import Downloader
from novel_scraper.exceptions import ChapterExtractionError
from novel_scraper.models import (
    ChapterContent,
    ChapterInfo,
    DownloadStatus,
    NovelMetadata,
)


class MockAdapter(BaseAdapter):
    """Mock adapter for offline testing."""

    name = "MockAdapter"
    domain = "mocksite.com"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.extract_call_count = {}

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return "mocksite.com" in url

    def get_novel_metadata(self, url: str) -> NovelMetadata:
        return NovelMetadata(
            title="Mock Novel",
            source_url="https://mocksite.com/novel",
            author="Mock Author",
            novel_id="mock-novel",
        )

    def discover_chapters(self, url: str) -> list[ChapterInfo]:
        return [
            ChapterInfo(url=f"https://mocksite.com/ch{i}", title=f"Chapter {i}", order_index=i, chapter_number=float(i))
            for i in range(1, 4)
        ]

    def extract_chapter(self, url: str) -> ChapterContent:
        self.extract_call_count[url] = self.extract_call_count.get(url, 0) + 1
        if "ch2" in url:
            raise ChapterExtractionError("Simulated failure for chapter 2")
        return ChapterContent(
            chapter_info=ChapterInfo(url=url, title="Ch", order_index=1),
            clean_html=f"<p>Content for {url}</p>",
            paragraphs=[f"Content for {url}"],
        )


def test_download_resumption_and_failure_resilience(tmp_path: Path):
    """Verify that failed chapters do not crash download and already-downloaded chapters are skipped."""
    config = Config(download_dir=str(tmp_path), request_delay=0.0)
    db = Database(tmp_path / "mock-novel.db")
    adapter = MockAdapter(config=config)

    downloader = Downloader(config=config, db=db, adapter=adapter)

    # First run: ch1 succeeds, ch2 fails, ch3 succeeds
    result = downloader.download_novel("https://mocksite.com/novel")

    assert result.total == 3
    assert result.downloaded == 2  # ch1 and ch3
    assert result.skipped == 0
    assert len(result.failed) == 1
    assert "ch2" in result.failed[0][0].url

    # Check database state
    chapters_in_db = db.get_chapters("mock-novel")
    assert chapters_in_db[0].status == DownloadStatus.COMPLETED
    assert chapters_in_db[1].status == DownloadStatus.FAILED
    assert chapters_in_db[2].status == DownloadStatus.COMPLETED

    # Verify call counts: ch1 called once, ch2 called once, ch3 called once
    assert adapter.extract_call_count["https://mocksite.com/ch1"] == 1
    assert adapter.extract_call_count["https://mocksite.com/ch2"] == 1
    assert adapter.extract_call_count["https://mocksite.com/ch3"] == 1

    # Second run without force: ch1 and ch3 are completed, should be skipped
    # ch2 is still failed and should be skipped unless resume or force
    result2 = downloader.download_novel("https://mocksite.com/novel")
    assert result2.downloaded == 0
    assert result2.skipped == 2

    # Now fix the mock adapter so ch2 succeeds
    class FixedMockAdapter(MockAdapter):
        def extract_chapter(self, url: str) -> ChapterContent:
            return ChapterContent(
                chapter_info=ChapterInfo(url=url, title="Ch", order_index=2),
                clean_html=f"<p>Fixed content for {url}</p>",
            )

    fixed_adapter = FixedMockAdapter(config=config)
    downloader_fixed = Downloader(config=config, db=db, adapter=fixed_adapter)

    # Resume run: should retry ch2
    result_resume = downloader_fixed.download_novel("https://mocksite.com/novel", resume_only=True)
    assert result_resume.downloaded == 1  # ch2 is downloaded!
    assert result_resume.skipped == 2     # ch1 and ch3 skipped

    # Verify all 3 chapters are now completed in DB
    stats = db.get_stats("mock-novel")
    assert stats["completed"] == 3
    assert stats["failed"] == 0
    assert stats["pending"] == 0
