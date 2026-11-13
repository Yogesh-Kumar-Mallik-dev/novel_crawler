"""Tests for alternate mirror fallback and network restore resilience."""

from unittest.mock import MagicMock, patch
import requests

from novel_scraper.config import Config
from novel_scraper.database import Database
from novel_scraper.downloader import Downloader
from novel_scraper.fallback import AlternateChapterFinder
from novel_scraper.models import (
    ChapterContent,
    ChapterInfo,
    ChapterRecord,
    DownloadStatus,
    NovelMetadata,
)


def test_search_mirrors_parsing():
    """Test DuckDuckGo HTML result parsing for mirror candidate links."""
    finder = AlternateChapterFinder()
    mock_session = MagicMock()

    mock_html = """
    <html>
        <body>
            <a class="result__url" href="https://novelfull.com/novel-title/chapter-532.html">novelfull.com</a>
            <a class="result__url" href="https://unrelated-domain.com/chapter-532">other</a>
            <a class="result__url" href="/l/?uddg=https%3A%2F%2Freadnovelfull.com%2Fnovel%2Fchapter-532.html">readnovelfull</a>
        </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_html
    mock_session.get.return_value = mock_resp
    finder.session = mock_session

    urls = finder._search_mirrors("Novel Title", 532)
    assert len(urls) == 2
    assert "https://novelfull.com/novel-title/chapter-532.html" in urls
    assert "https://readnovelfull.com/novel/chapter-532.html" in urls


def test_find_alternate_from_mirror(tmp_path):
    """Test successful recovery of a chapter from a mirror candidate URL."""
    finder = AlternateChapterFinder()
    mock_session = MagicMock()

    # Search response
    search_html = """
    <a class="result__url" href="https://novelfull.com/book/chapter-10.html">novelfull</a>
    """
    search_resp = MagicMock(status_code=200, text=search_html)

    # Content response
    content_html = """
    <html>
        <body>
            <div id="chr-content">
                <p>Paragraph one of the recovered mirror content.</p>
                <p>Paragraph two with additional cultivation details.</p>
                <p>Paragraph three describing the martial arts duel.</p>
                <p>Paragraph four concluding the intense encounter.</p>
                <p>Paragraph five setting up the next arc cleanly and safely.</p>
                <p>Paragraph six giving enough length to pass validation.</p>
            </div>
        </body>
    </html>
    """
    content_resp = MagicMock(status_code=200, text=content_html)

    mock_session.get.side_effect = [search_resp, content_resp]
    finder.session = mock_session

    res = finder.find_alternate(
        novel_title="Test Novel",
        chapter_number=10,
        chapter_title="Chapter 10",
        original_url="https://novelping.com/book/test/chap-10",
    )

    assert res is not None
    assert isinstance(res, ChapterContent)
    assert len(res.paragraphs) >= 5
    assert "martial arts duel" in res.paragraphs[2]


def test_find_alternate_wayback_fallback():
    """Test fallback to Wayback Machine when mirrors fail."""
    finder = AlternateChapterFinder()
    mock_session = MagicMock()

    # Mirror search returns nothing
    search_resp = MagicMock(status_code=200, text="<html><body>No results</body></html>")

    # Wayback API response
    wayback_api_resp = MagicMock(
        status_code=200,
        json=lambda: {
            "archived_snapshots": {
                "closest": {
                    "available": True,
                    "url": "https://web.archive.org/web/20260101/https://novelping.com/chap-1",
                }
            }
        },
    )

    # Wayback page response
    wayback_page_resp = MagicMock(
        status_code=200,
        text="""
        <html><body><div class="content">
            <p>Archived paragraph 1 with enough content text.</p>
            <p>Archived paragraph 2 with enough content text.</p>
            <p>Archived paragraph 3 with enough content text.</p>
            <p>Archived paragraph 4 with enough content text.</p>
            <p>Archived paragraph 5 with enough content text.</p>
            <p>Archived paragraph 6 with enough content text.</p>
        </div></body></html>
        """,
    )

    mock_session.get.side_effect = [search_resp, wayback_api_resp, wayback_page_resp]
    finder.session = mock_session

    res = finder.find_alternate(
        novel_title="Old Novel",
        chapter_number=1,
        chapter_title="Chapter 1",
        original_url="https://novelping.com/chap-1",
    )

    assert res is not None
    assert len(res.paragraphs) >= 5
    assert "Archived paragraph 1" in res.paragraphs[0]


def test_downloader_recovers_via_alternate(tmp_path):
    """Test Downloader using alternate mirror when primary adapter throws."""
    config = Config(download_dir=tmp_path)
    downloader = Downloader(config=config)

    mock_adapter = MagicMock()
    mock_adapter.extract_chapter.side_effect = Exception("Primary site 503 Service Unavailable")

    mock_alternate = ChapterContent(
        chapter_info=ChapterInfo(
            url="https://primary.com/c1",
            title="Chapter 1",
            order_index=1,
            chapter_number=1.0,
        ),
        clean_html="<p>Recovered</p>",
        paragraphs=["Recovered"],
        raw_html="<p>Recovered</p>",
    )
    downloader.alternate_finder.find_alternate = MagicMock(return_value=mock_alternate)

    db = Database(tmp_path / "test.db")
    rec = ChapterRecord(
        id=1,
        novel_id="test-book",
        order_index=1,
        chapter_number=1.0,
        title="Chapter 1",
        url="https://primary.com/c1",
        status=DownloadStatus.FAILED,
    )
    metadata = NovelMetadata(title="Test Book", source_url="https://primary.com/novel", novel_id="test-book")
    db.save_novel_metadata(metadata)
    db.save_chapters(
        [ChapterInfo(url="https://primary.com/c1", title="Chapter 1", order_index=1, chapter_number=1.0)],
        novel_id="test-book",
    )

    success = downloader._fetch_single_chapter(rec, mock_adapter, db, metadata)
    assert success is True

    # Check DB was marked completed
    chaps = db.get_chapters("test-book", status=DownloadStatus.COMPLETED)
    assert len(chaps) == 1
    assert chaps[0].content_html == "<p>Recovered</p>"


def test_network_down_error_detection():
    """Test network disconnection detection."""
    downloader = Downloader()

    exc1 = requests.exceptions.ConnectionError("[Errno 101] Network is unreachable")
    assert downloader._is_network_down_error(exc1) is True

    exc2 = requests.exceptions.ConnectionError("Temporary failure in name resolution")
    assert downloader._is_network_down_error(exc2) is True

    exc3 = ValueError("Invalid HTML element")
    assert downloader._is_network_down_error(exc3) is False
