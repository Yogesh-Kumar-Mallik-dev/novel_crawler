"""Command-line interface for NovelScraper."""

import argparse
import sys
from pathlib import Path
from typing import Optional

from novel_scraper.adapters import get_adapter, get_all_adapters
from novel_scraper.chapter_discovery import ChapterDiscoverer
from novel_scraper.config import Config, load_config, save_config
from novel_scraper.database import Database
from novel_scraper.downloader import Downloader
from novel_scraper.epub_builder import EpubBuilder
from novel_scraper.exceptions import NovelScraperError
from novel_scraper.models import DownloadStatus
from novel_scraper.utils import sanitize_filename


def handle_download(args: argparse.Namespace, config: Config) -> int:
    """Handle novel download command."""
    if args.delay is not None:
        config.request_delay = args.delay
    if args.timeout is not None:
        config.request_timeout = args.timeout

    downloader = Downloader(config=config)
    try:
        result = downloader.download_novel(
            url=args.url,
            start_chapter=args.start_chapter,
            end_chapter=args.end_chapter,
            force=args.force,
        )
    except NovelScraperError as exc:
        print(f"Error during download: {exc}", file=sys.stderr)
        return 1

    print("\nDownload Summary:")
    print(f"  Novel: {result.metadata.title}")
    print(f"  Target chapters: {result.total}")
    print(f"  Downloaded now: {result.downloaded}")
    print(f"  Already downloaded (skipped): {result.skipped}")
    print(f"  Failed: {len(result.failed)}")

    if result.failed:
        print("\nFailed Chapters:")
        for rec, err in result.failed[:10]:
            print(f"  - {rec.title} ({rec.url}): {err}")
        if len(result.failed) > 10:
            print(f"  ... and {len(result.failed) - 10} more.")
        print("Run 'novel-scraper resume <URL>' to retry failed chapters.")

    if not args.no_epub and (result.downloaded > 0 or result.skipped > 0):
        print("\nBuilding EPUB file...")
        db = downloader.get_database_for_novel(result.metadata)
        completed_chapters = db.get_chapters(
            result.metadata.novel_id or sanitize_filename(result.metadata.title),
            status=DownloadStatus.COMPLETED,
        )
        if completed_chapters:
            builder = EpubBuilder(config=config)
            output_path = Path(args.output) if args.output else None
            epub_path = builder.build_epub(
                metadata=result.metadata,
                chapters=completed_chapters,
                output_path=output_path,
            )
            print(f"EPUB created successfully: {epub_path}")

    return 0 if not result.failed else 1


def handle_resume(args: argparse.Namespace, config: Config) -> int:
    """Handle resume command."""
    if args.delay is not None:
        config.request_delay = args.delay
    if args.timeout is not None:
        config.request_timeout = args.timeout

    downloader = Downloader(config=config)
    try:
        result = downloader.download_novel(
            url=args.url,
            resume_only=True,
        )
    except NovelScraperError as exc:
        print(f"Error during resume: {exc}", file=sys.stderr)
        return 1

    print("\nResume Summary:")
    print(f"  Novel: {result.metadata.title}")
    print(f"  Downloaded now: {result.downloaded}")
    print(f"  Skipped: {result.skipped}")
    print(f"  Failed: {len(result.failed)}")

    if not getattr(args, "no_epub", False) and (result.downloaded > 0 or result.skipped > 0):
        print("\nUpdating EPUB file...")
        db = downloader.get_database_for_novel(result.metadata)
        completed_chapters = db.get_chapters(
            result.metadata.novel_id or sanitize_filename(result.metadata.title),
            status=DownloadStatus.COMPLETED,
        )
        if completed_chapters:
            builder = EpubBuilder(config=config)
            output_path = Path(args.output) if getattr(args, "output", None) else None
            epub_path = builder.build_epub(
                metadata=result.metadata,
                chapters=completed_chapters,
                output_path=output_path,
            )
            print(f"EPUB updated successfully: {epub_path}")

    return 0 if not result.failed else 1


def handle_chapters(args: argparse.Namespace, config: Config) -> int:
    """List available chapters for a novel."""
    try:
        adapter = get_adapter(args.url, config=config)
        metadata = adapter.get_novel_metadata(args.url)
        print(f"Novel: {metadata.title}")
        print(f"Author: {metadata.author or 'Unknown'}")
        if metadata.genres:
            print(f"Genres: {', '.join(metadata.genres)}")
        print(f"Status: {metadata.status or 'Unknown'}\n")

        discoverer = ChapterDiscoverer(adapter=adapter, config=config)
        chapters = discoverer.discover(args.url)

        if args.start_chapter or args.end_chapter:
            chapters = discoverer.filter_chapters(
                chapters,
                start_chapter=args.start_chapter,
                end_chapter=args.end_chapter,
            )

        print(f"Discovered {len(chapters)} chapter(s):")
        limit = args.limit or len(chapters)
        for i, ch in enumerate(chapters[:limit], start=1):
            num_str = f" [#{ch.chapter_number}]" if ch.chapter_number is not None else ""
            print(f"  {i}. {ch.title}{num_str}")
            print(f"     URL: {ch.url}")

        if limit < len(chapters):
            print(f"\n  ... and {len(chapters) - limit} more chapters.")

        return 0
    except NovelScraperError as exc:
        print(f"Error discovering chapters: {exc}", file=sys.stderr)
        return 1


def handle_epub(args: argparse.Namespace, config: Config) -> int:
    """Generate EPUB from previously downloaded SQLite chapters."""
    try:
        adapter = get_adapter(args.url, config=config)
        metadata = adapter.get_novel_metadata(args.url)
        novel_id = metadata.novel_id or sanitize_filename(metadata.title)

        downloader = Downloader(config=config)
        db = downloader.get_database_for_novel(metadata)

        # Retrieve chapters from DB
        if getattr(args, "all_chapters", False):
            target_chapters = db.get_chapters(novel_id)
        else:
            target_chapters = db.get_chapters(novel_id, status=DownloadStatus.COMPLETED)
            if not target_chapters:
                all_ch = db.get_chapters(novel_id)
                if all_ch:
                    print(
                        f"No completed chapters found, but {len(all_ch)} chapter(s) exist in database.",
                        file=sys.stderr,
                    )
                    print("Use --all-chapters to compile all chapters into the EPUB.", file=sys.stderr)
                else:
                    print(f"No chapters found in database for novel '{metadata.title}'.", file=sys.stderr)
                return 1

        stats = db.get_stats(novel_id)
        print(
            f"Building EPUB for '{metadata.title}' with {len(target_chapters)} chapters "
            f"(Completed: {stats.get('completed', 0)}, Total in DB: {stats.get('total', 0)})..."
        )
        builder = EpubBuilder(config=config)
        output_path = Path(args.output) if args.output else None
        epub_path = builder.build_epub(
            metadata=metadata,
            chapters=target_chapters,
            output_path=output_path,
        )
        print(f"EPUB created successfully: {epub_path}")
        return 0
    except NovelScraperError as exc:
        print(f"Error creating EPUB: {exc}", file=sys.stderr)
        return 1


def handle_sites(args: argparse.Namespace, config: Config) -> int:
    """List supported website adapters."""
    adapters = get_all_adapters()
    print("Supported Websites:")
    for ad in adapters:
        print(f"  - {ad.name} (Domain: {ad.domain})")
    return 0


def handle_config(args: argparse.Namespace, config: Config) -> int:
    """View or update configuration settings."""
    if args.set:
        for item in args.set:
            if "=" not in item:
                print(f"Invalid key=value format: {item}", file=sys.stderr)
                return 1
            key, val = item.split("=", 1)
            key = key.strip()
            val = val.strip()

            if not hasattr(config, key):
                print(f"Unknown config key: {key}", file=sys.stderr)
                return 1

            target_type = type(getattr(config, key))
            try:
                if target_type == bool:
                    typed_val = val.lower() in ("true", "1", "yes")
                else:
                    typed_val = target_type(val)
                setattr(config, key, typed_val)
            except ValueError:
                print(f"Invalid value '{val}' for {key} (expected {target_type.__name__})", file=sys.stderr)
                return 1

        saved_path = save_config(config)
        print(f"Configuration saved to {saved_path}")

    # Display current configuration
    print("Current Configuration:")
    for k, v in config.to_dict().items():
        print(f"  {k}: {v}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser with subparsers."""
    parser = argparse.ArgumentParser(
        prog="novel-scraper",
        description="NovelScraper: A robust, modular novel-to-EPUB downloader and archiver.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. download
    p_dl = subparsers.add_parser("download", help="Download chapters and generate an EPUB.")
    p_dl.add_argument("url", help="Novel or chapter URL.")
    p_dl.add_argument("--all", action="store_true", help="Download all available chapters.")
    p_dl.add_argument("--start-chapter", type=float, help="Starting chapter number or index.")
    p_dl.add_argument("--end-chapter", type=float, help="Ending chapter number or index.")
    p_dl.add_argument("--force", action="store_true", help="Redownload already completed chapters.")
    p_dl.add_argument("--delay", type=float, help="Polite delay between requests (seconds).")
    p_dl.add_argument("--timeout", type=float, help="Request timeout (seconds).")
    p_dl.add_argument("--output", type=str, help="Custom path for the generated EPUB file.")
    p_dl.add_argument("--no-epub", action="store_true", help="Skip EPUB generation (database only).")
    p_dl.set_defaults(func=handle_download)

    # 2. resume
    p_res = subparsers.add_parser("resume", help="Resume interrupted download and retry failed chapters.")
    p_res.add_argument("url", help="Novel or chapter URL.")
    p_res.add_argument("--delay", type=float, help="Polite delay between requests (seconds).")
    p_res.add_argument("--timeout", type=float, help="Request timeout (seconds).")
    p_res.add_argument("--output", type=str, help="Custom path for the generated EPUB file.")
    p_res.set_defaults(func=handle_resume)

    # 3. chapters
    p_ch = subparsers.add_parser("chapters", help="List discovered chapters for a novel.")
    p_ch.add_argument("url", help="Novel or chapter URL.")
    p_ch.add_argument("--start-chapter", type=float, help="Starting chapter filter.")
    p_ch.add_argument("--end-chapter", type=float, help="Ending chapter filter.")
    p_ch.add_argument("--limit", type=int, default=25, help="Number of chapters to preview (default 25).")
    p_ch.set_defaults(func=handle_chapters)

    # 4. epub
    p_ep = subparsers.add_parser("epub", help="Generate EPUB from downloaded chapters in SQLite.")
    p_ep.add_argument("url", help="Novel or chapter URL.")
    p_ep.add_argument("--output", type=str, help="Custom output EPUB file path.")
    p_ep.add_argument(
        "--all-chapters",
        action="store_true",
        help="Include all chapters stored in database (including pending ones).",
    )
    p_ep.set_defaults(func=handle_epub)

    # 5. sites
    p_sites = subparsers.add_parser("sites", help="List supported novel websites.")
    p_sites.set_defaults(func=handle_sites)

    # 6. config
    p_cfg = subparsers.add_parser("config", help="View or modify application settings.")
    p_cfg.add_argument("--set", nargs="+", metavar="KEY=VALUE", help="Update settings, e.g. request_delay=1.0")
    p_cfg.set_defaults(func=handle_config)

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    """CLI entrypoint."""
    if argv is None:
        argv = sys.argv[1:]

    # Direct URL convenience: if first argument is a URL, default to 'download'
    known_commands = {
        "download",
        "resume",
        "chapters",
        "epub",
        "sites",
        "config",
        "-h",
        "--help",
        "-v",
        "--version",
    }
    if argv and argv[0] not in known_commands and not argv[0].startswith("-"):
        if argv[0].startswith(("http://", "https://")):
            argv = ["download"] + argv

    parser = build_parser()
    args = parser.parse_args(argv)

    config = load_config()

    try:
        sys.exit(args.func(args, config))
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
