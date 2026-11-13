"""SQLite persistence layer for NovelScraper."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from novel_scraper.exceptions import DatabaseError
from novel_scraper.models import (
    ChapterInfo,
    ChapterRecord,
    DownloadStatus,
    NovelMetadata,
)


class Database:
    """SQLite manager for tracking novel metadata and chapter download state."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a sqlite3 connection with row factory."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_db(self) -> None:
        """Initialize database tables and indexes."""
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS novels (
                    novel_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    author TEXT,
                    description TEXT,
                    cover_url TEXT,
                    genres TEXT,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    chapter_number REAL,
                    title TEXT NOT NULL,
                    url TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    content_html TEXT,
                    downloaded_at TIMESTAMP,
                    FOREIGN KEY (novel_id) REFERENCES novels(novel_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_chapters_novel_order
                    ON chapters(novel_id, order_index);
                CREATE INDEX IF NOT EXISTS idx_chapters_status
                    ON chapters(status);
                """
            )

    def save_novel_metadata(self, metadata: NovelMetadata) -> None:
        """Insert or update novel metadata."""
        novel_id = metadata.novel_id or metadata.title.lower().replace(" ", "-")
        genres_json = json.dumps(metadata.genres)
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO novels (
                    novel_id, title, source_url, author, description,
                    cover_url, genres, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(novel_id) DO UPDATE SET
                    title = excluded.title,
                    source_url = excluded.source_url,
                    author = excluded.author,
                    description = excluded.description,
                    cover_url = excluded.cover_url,
                    genres = excluded.genres,
                    status = excluded.status,
                    updated_at = excluded.updated_at;
                """,
                (
                    novel_id,
                    metadata.title,
                    metadata.source_url,
                    metadata.author,
                    metadata.description,
                    metadata.cover_url,
                    genres_json,
                    metadata.status,
                    now,
                ),
            )

    def get_novel_metadata(self, novel_id: str) -> Optional[NovelMetadata]:
        """Retrieve novel metadata by novel_id."""
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT novel_id, title, source_url, author, description, cover_url, genres, status
                FROM novels WHERE novel_id = ?;
                """,
                (novel_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            genres = []
            if row["genres"]:
                try:
                    genres = json.loads(row["genres"])
                except Exception:
                    genres = [g.strip() for g in row["genres"].split(",") if g.strip()]

            return NovelMetadata(
                title=row["title"],
                source_url=row["source_url"],
                author=row["author"],
                description=row["description"],
                cover_url=row["cover_url"],
                genres=genres,
                status=row["status"],
                novel_id=row["novel_id"],
            )

    def save_chapters(self, chapters: list[ChapterInfo], novel_id: str) -> None:
        """Insert or ignore discovered chapters."""
        with self._get_connection() as conn:
            # Ensure parent novel record exists so foreign key is satisfied
            conn.execute(
                """
                INSERT OR IGNORE INTO novels (novel_id, title, source_url)
                VALUES (?, ?, ?);
                """,
                (novel_id, novel_id.replace("-", " ").title(), ""),
            )

            for ch in chapters:
                conn.execute(
                    """
                    INSERT INTO chapters (
                        novel_id, order_index, chapter_number, title, url, status
                    ) VALUES (?, ?, ?, ?, ?, 'pending')
                    ON CONFLICT(url) DO UPDATE SET
                        order_index = excluded.order_index,
                        chapter_number = excluded.chapter_number,
                        title = excluded.title;
                    """,
                    (
                        novel_id,
                        ch.order_index,
                        ch.chapter_number,
                        ch.title,
                        ch.url,
                    ),
                )

    def mark_chapter_completed(self, url: str, content_html: str) -> None:
        """Mark chapter as completed and persist extracted clean HTML."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE chapters
                SET status = 'completed',
                    content_html = ?,
                    error_message = NULL,
                    downloaded_at = ?
                WHERE url = ?;
                """,
                (content_html, now, url),
            )

    def mark_chapter_failed(self, url: str, error_message: str) -> None:
        """Mark chapter as failed with error details."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE chapters
                SET status = 'failed',
                    error_message = ?
                WHERE url = ?;
                """,
                (error_message, url),
            )

    def reset_failed_chapters(self, novel_id: str) -> int:
        """Reset failed chapters back to pending for retry."""
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE chapters
                SET status = 'pending', error_message = NULL
                WHERE novel_id = ? AND status = 'failed';
                """,
                (novel_id,),
            )
            return cur.rowcount

    def reset_chapters_for_force(self, novel_id: str, urls: Optional[list[str]] = None) -> int:
        """Reset specified or all chapters back to pending when force redownload is requested."""
        with self._get_connection() as conn:
            if urls:
                placeholders = ",".join("?" for _ in urls)
                cur = conn.execute(
                    f"""
                    UPDATE chapters
                    SET status = 'pending', error_message = NULL, content_html = NULL, downloaded_at = NULL
                    WHERE novel_id = ? AND url IN ({placeholders});
                    """,
                    [novel_id] + urls,
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE chapters
                    SET status = 'pending', error_message = NULL, content_html = NULL, downloaded_at = NULL
                    WHERE novel_id = ?;
                    """,
                    (novel_id,),
                )
            return cur.rowcount

    def get_chapters(
        self,
        novel_id: str,
        status: Optional[DownloadStatus] = None,
    ) -> list[ChapterRecord]:
        """Fetch chapters for a novel ordered by order_index."""
        query = "SELECT * FROM chapters WHERE novel_id = ?"
        params: list[object] = [novel_id]

        if status:
            query += " AND status = ?"
            params.append(status.value)

        query += " ORDER BY order_index ASC;"

        with self._get_connection() as conn:
            cur = conn.execute(query, params)
            records = []
            for row in cur.fetchall():
                downloaded_at = None
                if row["downloaded_at"]:
                    try:
                        downloaded_at = datetime.fromisoformat(row["downloaded_at"])
                    except Exception:
                        pass
                records.append(
                    ChapterRecord(
                        id=row["id"],
                        novel_id=row["novel_id"],
                        order_index=row["order_index"],
                        chapter_number=row["chapter_number"],
                        title=row["title"],
                        url=row["url"],
                        status=DownloadStatus(row["status"]),
                        error_message=row["error_message"],
                        content_html=row["content_html"],
                        downloaded_at=downloaded_at,
                    )
                )
            return records

    def get_stats(self, novel_id: str) -> dict[str, int]:
        """Return counts of total, completed, pending, and failed chapters."""
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT status, count(*) as cnt
                FROM chapters
                WHERE novel_id = ?
                GROUP BY status;
                """,
                (novel_id,),
            )
            counts = {row["status"]: row["cnt"] for row in cur.fetchall()}
            total = sum(counts.values())
            return {
                "total": total,
                "completed": counts.get("completed", 0),
                "pending": counts.get("pending", 0),
                "failed": counts.get("failed", 0),
            }
