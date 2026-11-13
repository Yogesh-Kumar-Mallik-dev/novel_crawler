"""Data models for NovelScraper."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class DownloadStatus(str, Enum):
    """Status of chapter downloads."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class NovelMetadata:
    """Metadata representing a web novel."""

    title: str
    source_url: str
    author: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    genres: list[str] = field(default_factory=list)
    status: Optional[str] = None
    novel_id: Optional[str] = None


@dataclass
class ChapterInfo:
    """Basic chapter descriptor obtained during discovery."""

    url: str
    title: str
    order_index: int
    chapter_number: Optional[float] = None
    novel_url: Optional[str] = None


@dataclass
class ChapterContent:
    """Full chapter content extracted from a webpage."""

    chapter_info: ChapterInfo
    clean_html: str
    paragraphs: list[str] = field(default_factory=list)
    raw_html: Optional[str] = None


@dataclass
class ChapterRecord:
    """Chapter record stored in SQLite database."""

    id: Optional[int]
    novel_id: str
    order_index: int
    chapter_number: Optional[float]
    title: str
    url: str
    status: DownloadStatus
    error_message: Optional[str] = None
    content_html: Optional[str] = None
    downloaded_at: Optional[datetime] = None
