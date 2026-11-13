"""Tests for URL recognition, chapter discovery, ordering, and deduplication."""

from pathlib import Path
import pytest
from unittest.mock import MagicMock

from novel_scraper.adapters import get_adapter
from novel_scraper.adapters.novelping import NovelPingAdapter
from novel_scraper.chapter_discovery import ChapterDiscoverer
from novel_scraper.exceptions import UnsupportedWebsiteError
from novel_scraper.models import ChapterInfo

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_url_recognition():
    """Verify that NovelPingAdapter recognizes valid URLs and rejects unsupported domains."""
    valid_urls = [
        "https://novelping.com/book/journey-to-become-a-true-god",
        "https://novelping.com/book/journey-to-become-a-true-god/chapter-1",
        "https://www.novelping.com/book/dual-cultivation-novel",
        "http://novelping.com/book/pocket-hunting-dimension/chapter-50",
    ]
    for url in valid_urls:
        assert NovelPingAdapter.can_handle(url) is True
        adapter = get_adapter(url)
        assert isinstance(adapter, NovelPingAdapter)

    invalid_urls = [
        "https://example.com/novel/123",
        "https://readlightnovel.me/some-novel",
        "https://wuxiaworld.com/novel/coiling-dragon",
    ]
    for url in invalid_urls:
        assert NovelPingAdapter.can_handle(url) is False
        with pytest.raises(UnsupportedWebsiteError):
            get_adapter(url, allow_generic=False)


def test_chapter_discovery_from_archive_fixture():
    """Test discovering chapters from the saved offline archive fixture."""
    archive_file = FIXTURES_DIR / "novelping_archive.html"
    assert archive_file.exists(), "novelping_archive.html fixture missing"

    with open(archive_file, "r", encoding="utf-8") as f:
        archive_html = f.read()

    adapter = NovelPingAdapter()
    chapters = adapter._parse_archive_html(
        archive_html,
        book_url="https://novelping.com/book/journey-to-become-a-true-god",
    )

    assert len(chapters) > 4000
    first = chapters[0]
    assert first.order_index == 1
    assert first.chapter_number == 1.0
    assert first.url == "https://novelping.com/book/journey-to-become-a-true-god/chapter-1"
    assert "Chapter 1" in first.title

    # Verify sequential ordering
    for idx, ch in enumerate(chapters, start=1):
        assert ch.order_index == idx


def test_duplicate_chapter_removal():
    """Verify that duplicate chapter URLs are detected and skipped without losing order."""
    duplicate_html = """
    <template data-chapter-item-template>
        <li data-chapter-item><a href="/book/test/chapter-1" title="Chapter 1">Chapter 1</a></li>
        <li data-chapter-item><a href="/book/test/chapter-1" title="Chapter 1 Duplicate">Chapter 1</a></li>
        <li data-chapter-item><a href="/book/test/chapter-2" title="Chapter 2">Chapter 2</a></li>
        <li data-chapter-item><a href="/book/test/chapter-2" title="Chapter 2 Duplicate">Chapter 2</a></li>
        <li data-chapter-item><a href="/book/test/chapter-3" title="Chapter 3">Chapter 3</a></li>
    </template>
    """
    adapter = NovelPingAdapter()
    chapters = adapter._parse_archive_html(duplicate_html, book_url="https://novelping.com/book/test")

    assert len(chapters) == 3
    assert [ch.order_index for ch in chapters] == [1, 2, 3]
    assert [ch.url for ch in chapters] == [
        "https://novelping.com/book/test/chapter-1",
        "https://novelping.com/book/test/chapter-2",
        "https://novelping.com/book/test/chapter-3",
    ]


def test_chapter_range_filtering():
    """Test chapter range filtering with numeric and non-numeric chapters."""
    sample_chapters = [
        ChapterInfo(url="http://x/prologue", title="Prologue", order_index=1, chapter_number=None),
        ChapterInfo(url="http://x/c1", title="Chapter 1", order_index=2, chapter_number=1.0),
        ChapterInfo(url="http://x/c2", title="Chapter 2", order_index=3, chapter_number=2.0),
        ChapterInfo(url="http://x/c2.5", title="Chapter 2.5", order_index=4, chapter_number=2.5),
        ChapterInfo(url="http://x/c3", title="Chapter 3", order_index=5, chapter_number=3.0),
        ChapterInfo(url="http://x/c4", title="Chapter 4", order_index=6, chapter_number=4.0),
        ChapterInfo(url="http://x/epilogue", title="Epilogue", order_index=7, chapter_number=None),
    ]

    # 1. Start chapter 2, End chapter 3
    filtered = ChapterDiscoverer.filter_chapters(sample_chapters, start_chapter=2.0, end_chapter=3.0)
    assert len(filtered) == 3
    assert [ch.title for ch in filtered] == ["Chapter 2", "Chapter 2.5", "Chapter 3"]

    # 2. Start chapter 3 only
    filtered = ChapterDiscoverer.filter_chapters(sample_chapters, start_chapter=3.0)
    assert len(filtered) == 3  # Chapter 3, Chapter 4, and Epilogue (order_index=7 > 3)

    # 3. End chapter 2
    filtered = ChapterDiscoverer.filter_chapters(sample_chapters, end_chapter=2.0)
    assert len(filtered) == 3  # Prologue (order_index=1 <= 2), Chapter 1, Chapter 2

    # 4. No filter
    filtered = ChapterDiscoverer.filter_chapters(sample_chapters)
    assert len(filtered) == len(sample_chapters)
