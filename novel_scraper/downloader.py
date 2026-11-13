"""Sequential chapter downloader with SQLite persistence and resume capability."""

import logging
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from tqdm import tqdm

from novel_scraper.adapters.base import BaseAdapter, get_adapter
from novel_scraper.chapter_discovery import ChapterDiscoverer
from novel_scraper.config import Config
from novel_scraper.database import Database
from novel_scraper.exceptions import ChapterExtractionError, NetworkError
from novel_scraper.models import (
    ChapterInfo,
    ChapterRecord,
    DownloadStatus,
    NovelMetadata,
)
from novel_scraper.utils import create_session, sanitize_filename

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Summary of a download execution."""

    metadata: NovelMetadata
    total: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: list[tuple[ChapterRecord, str]] = field(default_factory=list)
    interrupted: bool = False
    db_path: Optional[Path] = None


class Downloader:
    """Manages sequential chapter downloads with resume support and rate limiting."""

    def __init__(
        self,
        config: Optional[Config] = None,
        db: Optional[Database] = None,
        adapter: Optional[BaseAdapter] = None,
    ):
        self.config = config or Config()
        self.session = create_session(self.config)
        self.adapter = adapter
        self.db = db
        self.interrupted = False

    def _setup_signal_handler(self) -> None:
        """Register graceful SIGINT (Ctrl+C) handler."""
        def handler(sig, frame):
            print("\nInterrupt received! Finishing current task and saving progress...")
            self.interrupted = True

        signal.signal(signal.SIGINT, handler)

    def get_database_for_novel(self, metadata: NovelMetadata) -> Database:
        """Get or initialize the SQLite database for a novel."""
        if self.db:
            return self.db
        download_dir = Path(self.config.download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)
        db_filename = sanitize_filename(metadata.novel_id or metadata.title) + ".db"
        return Database(download_dir / db_filename)

    def download_novel(
        self,
        url: str,
        start_chapter: Optional[float] = None,
        end_chapter: Optional[float] = None,
        force: bool = False,
        resume_only: bool = False,
    ) -> DownloadResult:
        """Download novel chapters with SQLite tracking and resume support."""
        self._setup_signal_handler()
        self.interrupted = False

        adapter = self.adapter or get_adapter(url, session=self.session, config=self.config)

        # 1. Fetch novel metadata
        print(f"Fetching novel metadata for {url}...")
        metadata = adapter.get_novel_metadata(url)
        print(f"Found novel: {metadata.title} (Author: {metadata.author or 'Unknown'})")

        # 2. Setup SQLite persistence
        db = self.get_database_for_novel(metadata)
        db.save_novel_metadata(metadata)
        novel_id = metadata.novel_id or sanitize_filename(metadata.title)

        # 3. Discover chapters
        print("Discovering chapters...")
        discoverer = ChapterDiscoverer(adapter=adapter, config=self.config)
        all_chapters = discoverer.discover(url)
        print(f"Discovered {len(all_chapters)} chapters.")

        # 4. Filter chapters according to requested range
        target_chapters = discoverer.filter_chapters(
            all_chapters,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        print(f"Targeting {len(target_chapters)} chapters for download.")

        # Save all discovered chapters to DB
        db.save_chapters(all_chapters, novel_id=novel_id)

        target_urls = [ch.url for ch in target_chapters]

        if force:
            print("Force flag set: resetting target chapters to pending...")
            db.reset_chapters_for_force(novel_id, urls=target_urls)
        elif resume_only:
            # If resuming, reset previously failed chapters to pending
            reopened = db.reset_failed_chapters(novel_id)
            if reopened > 0:
                print(f"Reset {reopened} previously failed chapter(s) for retry.")

        # Load current status of chapters from DB
        db_records = {rec.url: rec for rec in db.get_chapters(novel_id)}

        to_download: list[ChapterRecord] = []
        skipped_count = 0

        for ch in target_chapters:
            rec = db_records.get(ch.url)
            if rec and rec.status == DownloadStatus.COMPLETED and not force:
                skipped_count += 1
            elif rec:
                to_download.append(rec)

        result = DownloadResult(
            metadata=metadata,
            total=len(target_chapters),
            skipped=skipped_count,
            db_path=db.db_path,
        )

        if not to_download:
            print(f"All {len(target_chapters)} chapters are already downloaded.")
            return result

        print(f"Downloading {len(to_download)} chapters ({skipped_count} already downloaded)...")

        with tqdm(
            total=len(target_chapters),
            initial=skipped_count,
            unit="chap",
            desc="Progress",
            dynamic_ncols=True,
        ) as pbar:
            for rec in to_download:
                if self.interrupted:
                    result.interrupted = True
                    print("\nDownload stopped by user.")
                    break

                # Apply polite delay between requests
                if self.config.request_delay > 0:
                    time.sleep(self.config.request_delay)

                pbar.set_postfix_str(rec.title[:25])

                try:
                    content = adapter.extract_chapter(rec.url)
                    db.mark_chapter_completed(rec.url, content.clean_html)
                    result.downloaded += 1
                    pbar.update(1)
                except (ChapterExtractionError, NetworkError, Exception) as exc:
                    err_msg = str(exc)
                    logger.warning("Failed to download chapter %s (%s): %s", rec.title, rec.url, err_msg)
                    db.mark_chapter_failed(rec.url, err_msg)
                    result.failed.append((rec, err_msg))
                    pbar.update(1)

        return result
