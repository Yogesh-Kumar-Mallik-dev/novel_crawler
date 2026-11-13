"""Tests for SQLite persistence, state tracking, and download resumption."""

from pathlib import Path
import pytest

from novel_scraper.database import Database
from novel_scraper.models import (
    ChapterInfo,
    DownloadStatus,
    NovelMetadata,
)


def test_database_initialization_and_metadata(tmp_path: Path):
    """Test creating SQLite database and saving/retrieving novel metadata."""
    db_file = tmp_path / "test_novel.db"
    db = Database(db_file)

    meta = NovelMetadata(
        title="Testing SQLite Novel",
        source_url="https://novelping.com/book/testing-sqlite",
        author="Great Author",
        description="Testing persistence",
        genres=["Action", "Cultivation"],
        status="Completed",
        novel_id="testing-sqlite",
    )

    db.save_novel_metadata(meta)
    retrieved = db.get_novel_metadata("testing-sqlite")

    assert retrieved is not None
    assert retrieved.title == "Testing SQLite Novel"
    assert retrieved.author == "Great Author"
    assert retrieved.genres == ["Action", "Cultivation"]
    assert retrieved.status == "Completed"


def test_database_chapter_lifecycle(tmp_path: Path):
    """Test saving chapters, updating status, and tracking counts."""
    db_file = tmp_path / "test_chapters.db"
    db = Database(db_file)

    chapters = [
        ChapterInfo(
            url="https://example.com/c1",
            title="Chapter 1",
            order_index=1,
            chapter_number=1.0,
        ),
        ChapterInfo(
            url="https://example.com/c2",
            title="Chapter 2",
            order_index=2,
            chapter_number=2.0,
        ),
        ChapterInfo(
            url="https://example.com/c3",
            title="Chapter 3",
            order_index=3,
            chapter_number=3.0,
        ),
    ]

    db.save_chapters(chapters, novel_id="test-novel")

    stats = db.get_stats("test-novel")
    assert stats["total"] == 3
    assert stats["pending"] == 3
    assert stats["completed"] == 0
    assert stats["failed"] == 0

    # Mark c1 as completed
    db.mark_chapter_completed("https://example.com/c1", "<p>Chapter 1 content</p>")
    # Mark c2 as failed
    db.mark_chapter_failed("https://example.com/c2", "HTTP 500 Server Error")

    stats = db.get_stats("test-novel")
    assert stats["completed"] == 1
    assert stats["failed"] == 1
    assert stats["pending"] == 1

    records = db.get_chapters("test-novel")
    assert records[0].status == DownloadStatus.COMPLETED
    assert records[0].content_html == "<p>Chapter 1 content</p>"
    assert records[1].status == DownloadStatus.FAILED
    assert records[1].error_message == "HTTP 500 Server Error"
    assert records[2].status == DownloadStatus.PENDING

    # Test resetting failed chapters
    reopened = db.reset_failed_chapters("test-novel")
    assert reopened == 1

    records = db.get_chapters("test-novel")
    assert records[1].status == DownloadStatus.PENDING
    assert records[1].error_message is None

    # Test force reset
    db.reset_chapters_for_force("test-novel")
    stats = db.get_stats("test-novel")
    assert stats["pending"] == 3
    assert stats["completed"] == 0
