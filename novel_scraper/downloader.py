"""Sequential chapter downloader with SQLite persistence, network guard, and alternate mirror fallbacks."""

import logging
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import requests
from tqdm import tqdm

from novel_scraper.adapters.base import BaseAdapter, get_adapter
from novel_scraper.chapter_discovery import ChapterDiscoverer
from novel_scraper.config import Config
from novel_scraper.database import Database
from novel_scraper.exceptions import ChapterExtractionError, NetworkError
from novel_scraper.fallback import AlternateChapterFinder
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
    recovered_from_alternate: int = 0
    skipped: int = 0
    failed: list[tuple[ChapterRecord, str]] = field(default_factory=list)
    interrupted: bool = False
    db_path: Optional[Path] = None


class Downloader:
    """Manages sequential chapter downloads with resume support, network guards, and alternate sources."""

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
        self.alternate_finder = AlternateChapterFinder(session=self.session)

    def _setup_signal_handler(self) -> None:
        """Register graceful SIGINT (Ctrl+C) handler."""
        def handler(sig, frame):
            print("\nInterrupt received! Finishing current task and saving progress...")
            self.interrupted = True

        signal.signal(signal.SIGINT, handler)

    def _is_network_down_error(self, exc: Exception) -> bool:
        """Check if exception represents local network disconnection."""
        msg = str(exc).lower()
        return any(
            err in msg
            for err in [
                "network is unreachable",
                "failed to establish a new connection",
                "nameresolutionerror",
                "connection refused",
                "temporary failure in name resolution",
                "errno 101",
            ]
        )

    def _wait_for_network_restore(self, max_wait_seconds: int = 45, check_interval: int = 5) -> bool:
        """Pause execution and poll for network restoration."""
        print("\n[!] Local network disconnected. Pausing and waiting for connection to restore...")
        start = time.time()
        while time.time() - start < max_wait_seconds:
            if self.interrupted:
                return False
            time.sleep(check_interval)
            try:
                # Fast connectivity check
                self.session.get("https://1.1.1.1", timeout=3.0)
                print("[+] Network connection restored! Resuming downloads...\n")
                return True
            except Exception:
                pass
        print("[!] Network did not recover within timeout period.")
        return False

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
        retry_failed_only: bool = False,
    ) -> DownloadResult:
        """Download novel chapters with SQLite tracking, network resilience, and alternate sources."""
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

        # 3. Handle retry_failed_only mode directly
        if retry_failed_only:
            failed_records = db.get_chapters(novel_id, status=DownloadStatus.FAILED)
            if not failed_records:
                print(f"No failed chapters found in database for '{metadata.title}'.")
                return DownloadResult(metadata=metadata, total=0, db_path=db.db_path)

            print(f"Retrying {len(failed_records)} previously failed chapter(s)...")
            return self._execute_download_loop(
                records=failed_records,
                adapter=adapter,
                db=db,
                metadata=metadata,
                skipped_initial=0,
                total_count=len(failed_records),
            )

        # 4. Discover chapters
        print("Discovering chapters...")
        discoverer = ChapterDiscoverer(adapter=adapter, config=self.config)
        all_chapters = discoverer.discover(url)
        print(f"Discovered {len(all_chapters)} chapters.")

        # 5. Filter chapters according to requested range
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

        if not to_download:
            print(f"All {len(target_chapters)} chapters are already downloaded.")
            return DownloadResult(
                metadata=metadata,
                total=len(target_chapters),
                skipped=skipped_count,
                db_path=db.db_path,
            )

        print(f"Downloading {len(to_download)} chapters ({skipped_count} already downloaded)...")

        return self._execute_download_loop(
            records=to_download,
            adapter=adapter,
            db=db,
            metadata=metadata,
            skipped_initial=skipped_count,
            total_count=len(target_chapters),
        )

    def _execute_download_loop(
        self,
        records: list[ChapterRecord],
        adapter: BaseAdapter,
        db: Database,
        metadata: NovelMetadata,
        skipped_initial: int,
        total_count: int,
    ) -> DownloadResult:
        """Core download loop with network guards, mirror fallbacks, and retry passes."""
        result = DownloadResult(
            metadata=metadata,
            total=total_count,
            skipped=skipped_initial,
            db_path=db.db_path,
        )

        with tqdm(
            total=total_count,
            initial=skipped_initial,
            unit="chap",
            desc="Progress",
            dynamic_ncols=True,
        ) as pbar:
            for rec in records:
                if self.interrupted:
                    result.interrupted = True
                    print("\nDownload stopped by user.")
                    break

                if self.config.request_delay > 0:
                    time.sleep(self.config.request_delay)

                pbar.set_postfix_str(rec.title[:25])

                success = self._fetch_single_chapter(rec, adapter, db, metadata)
                if success:
                    result.downloaded += 1
                else:
                    result.failed.append((rec, rec.error_message or "Fetch failed"))

                pbar.update(1)

        # Automatic second-pass retry for transiently failed chapters
        if result.failed and not self.interrupted:
            failed_to_retry = [item[0] for item in result.failed]
            print(f"\n[!] Automatically retrying {len(failed_to_retry)} failed chapter(s) with alternate fallbacks...")
            recovered_items = []
            for rec in failed_to_retry:
                if self.interrupted:
                    break
                time.sleep(max(1.0, self.config.request_delay))
                if self._fetch_single_chapter(rec, adapter, db, metadata):
                    recovered_items.append(rec)
                    result.downloaded += 1

            # Update failed list removing recovered ones
            recovered_urls = {r.url for r in recovered_items}
            result.failed = [item for item in result.failed if item[0].url not in recovered_urls]

        return result

    def _fetch_single_chapter(
        self,
        rec: ChapterRecord,
        adapter: BaseAdapter,
        db: Database,
        metadata: NovelMetadata,
    ) -> bool:
        """Attempt to fetch chapter via primary adapter, then network restore, then alternate mirrors."""
        # 1. Primary adapter fetch
        try:
            content = adapter.extract_chapter(rec.url)
            db.mark_chapter_completed(rec.url, content.clean_html)
            return True
        except Exception as exc:
            err_msg = str(exc)

            # Check for network disconnection
            if self._is_network_down_error(exc):
                restored = self._wait_for_network_restore()
                if restored and not self.interrupted:
                    try:
                        content = adapter.extract_chapter(rec.url)
                        db.mark_chapter_completed(rec.url, content.clean_html)
                        return True
                    except Exception as retry_exc:
                        err_msg = str(retry_exc)

            # 2. Primary fetch failed: search alternate mirror sources!
            logger.info("Primary fetch failed for %s. Searching alternate mirrors...", rec.title)
            alt_content = self.alternate_finder.find_alternate(
                novel_title=metadata.title,
                chapter_number=rec.chapter_number,
                chapter_title=rec.title,
                original_url=rec.url,
            )
            if alt_content:
                db.mark_chapter_completed(rec.url, alt_content.clean_html)
                return True

            # If all failed, mark failed in DB
            db.mark_chapter_failed(rec.url, err_msg)
            rec.error_message = err_msg
            return False
