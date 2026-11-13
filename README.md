# NovelScraper – Python Novel-to-EPUB Downloader

A robust, modular Python command-line application that scrapes publicly accessible web novel chapters, stores them with SQLite persistence, and compiles them into standards-compliant EPUB 3 digital books.

---

## Features

- **Modular Website Adapter Architecture**: Add support for any web novel platform simply by implementing a `BaseAdapter` subclass without modifying core application logic.
- **NovelPing Adapter**: Full support for [NovelPing](https://novelping.com), including metadata extraction, full archive chapter discovery (over 4,600+ chapters), and noise-free chapter content extraction.
- **SQLite Persistence & Resumption**: All metadata and chapter states (`pending`, `completed`, `failed`) are stored locally in SQLite (`downloads/<novel_id>.db`). Interrupted downloads can be resumed at any time without redownloading completed chapters.
- **Fault-Tolerant & Polite Crawling**: Configurable request delay, exponential backoff retries on network failures, graceful `Ctrl+C` interrupt handling, and per-chapter failure recovery.
- **Strict Content Sanitization**: Decomposes ads, social buttons, scripts, hidden trackers, and navigation elements while preserving semantic text (`<p>`, `<em>`, `<strong>`, `<i>`, `<b>`, `<br>`, headings, and clean formatting).
- **Standards-Compliant EPUB 3 Generation**: Builds validated EPUB 3 archives complete with cover image, Dublin Core metadata, table of contents (NCX + Nav), and typographic CSS styling.
- **Flexible CLI**: Rich command-line options for listing chapters, downloading entire novels, downloading specific ranges, building EPUBs from existing SQLite databases, and managing configuration.

---

## Architecture

```
novel-scraper/
├── novel_scraper/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                  # Command-line interface and subcommands
│   ├── config.py               # Application settings and persistence
│   ├── downloader.py           # Sequential download engine with SQLite tracking
│   ├── chapter_discovery.py    # Discovery and chapter range filtering
│   ├── content_extractor.py    # HTML cleaner and XHTML paragraph sanitizer
│   ├── epub_builder.py         # EPUB 3 packaging, metadata, TOC, and validation
│   ├── database.py             # SQLite persistence layer and state manager
│   ├── models.py               # Typed dataclasses (NovelMetadata, ChapterInfo, etc.)
│   ├── exceptions.py           # Custom exception hierarchy
│   ├── utils.py                # Network sessions, retries, filename sanitization
│   └── adapters/
│       ├── __init__.py         # Registry and adapter discovery
│       ├── base.py             # Abstract BaseAdapter contract
│       └── novelping.py        # NovelPing.com website adapter
├── tests/
│   ├── test_cli.py             # CLI parser and argument tests
│   ├── test_database.py        # SQLite persistence and state tests
│   ├── test_discovery.py       # Discovery, deduplication, and ordering tests
│   ├── test_downloader.py      # Resumption, failure handling, and retry tests
│   ├── test_epub.py            # EPUB 3 validation tests
│   ├── test_extraction.py      # HTML sanitization and noise removal tests
│   ├── test_retry.py           # HTTP backoff and retry tests
│   └── fixtures/               # Offline HTML test fixtures
├── downloads/                  # Output directory for SQLite DBs and EPUBs
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## Installation

### Prerequisites

- Python 3.12 or newer
- `pip`

### Setup Virtual Environment

```bash
cd novel-scraper

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install novel-scraper in editable development mode
pip install -e .
```

---

## Usage Guide

The CLI can be invoked either as `novel-scraper` or via `python -m novel_scraper`.

### 1. Discover and List Chapters

Inspect a novel, its author, genres, and preview available chapters without downloading:

```bash
# Preview the first 25 chapters
novel-scraper chapters https://novelping.com/book/journey-to-become-a-true-god/chapter-1

# Preview chapters with custom limit and range
novel-scraper chapters https://novelping.com/book/journey-to-become-a-true-god --start-chapter 1 --end-chapter 50 --limit 10
```

### 2. Download Chapters and Build EPUB

#### Download a Specific Chapter Range:

```bash
novel-scraper download https://novelping.com/book/journey-to-become-a-true-god/chapter-1 --start-chapter 1 --end-chapter 50
```

#### Download an Entire Novel:

```bash
novel-scraper download https://novelping.com/book/journey-to-become-a-true-god --all
```

#### Force Redownload:

Redownload chapters even if they are already marked as completed in SQLite:

```bash
novel-scraper download https://novelping.com/book/journey-to-become-a-true-god --start-chapter 1 --end-chapter 10 --force
```

#### Polite Crawling Options:

Tune delay between requests and HTTP timeout:

```bash
novel-scraper download https://novelping.com/book/journey-to-become-a-true-god \
  --start-chapter 1 --end-chapter 100 \
  --delay 1.0 \
  --timeout 25.0
```

### 3. Resume Interrupted Downloads

If a download is interrupted by `Ctrl+C` or a network outage, resume it with:

```bash
novel-scraper resume https://novelping.com/book/journey-to-become-a-true-god
```

This will automatically:
- Skip all chapters already downloaded successfully.
- Reset any previously failed chapters back to `pending`.
- Recompile the EPUB with all completed chapters upon completion.

### 4. Rebuild EPUB from Local Database

Generate an EPUB from previously downloaded chapters stored in SQLite without hitting the remote website:

```bash
# Build EPUB with all completed chapters
novel-scraper epub https://novelping.com/book/journey-to-become-a-true-god

# Build EPUB including all chapters registered in DB (including pending chapters)
novel-scraper epub https://novelping.com/book/journey-to-become-a-true-god --all-chapters

# Custom output path
novel-scraper epub https://novelping.com/book/journey-to-become-a-true-god --all-chapters --output ~/MyNovel.epub
```

### 5. View Supported Websites

```bash
novel-scraper sites
```

Output:
```
Supported Websites:
  - NovelPing (Domain: novelping.com)
```

### 6. Configuration Management

View or update global settings stored in `~/.config/novel-scraper/config.json`:

```bash
# View configuration
novel-scraper config

# Update configuration parameters
novel-scraper config --set request_delay=1.0 max_retries=5 request_timeout=30.0
```

---

## Configuration Options

| Key | Type | Default | Description |
|---|---|---|---|
| `request_timeout` | float | `20.0` | Maximum seconds to wait for HTTP response |
| `request_delay` | float | `0.5` | Polite delay (in seconds) between sequential chapter requests |
| `max_retries` | int | `3` | Number of retry attempts on 429 / 5xx HTTP responses |
| `backoff_factor` | float | `1.5` | Exponential backoff multiplier for retries |
| `user_agent` | string | Modern Chrome | User-Agent header sent with requests |
| `download_dir` | string | `downloads` | Local directory for SQLite databases and EPUBs |

---

## Adding a New Website Adapter

To support a new web novel website, create a new adapter module in `novel_scraper/adapters/<sitename>.py`:

```python
from novel_scraper.adapters.base import BaseAdapter, register_adapter
from novel_scraper.models import NovelMetadata, ChapterInfo, ChapterContent
from novel_scraper.content_extractor import ContentExtractor

@register_adapter
class MySiteAdapter(BaseAdapter):
    name = "MySite"
    domain = "mysite.com"

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return "mysite.com" in url.lower()

    def get_novel_metadata(self, url: str) -> NovelMetadata:
        # Fetch book page, parse title, author, cover_url, etc.
        ...

    def discover_chapters(self, url: str) -> list[ChapterInfo]:
        # Parse chapter listing or pagination, return ordered ChapterInfo list
        ...

    def extract_chapter(self, url: str) -> ChapterContent:
        # Extract title and clean content with ContentExtractor
        ...
```

Export your adapter in `novel_scraper/adapters/__init__.py`. It will automatically be registered and recognized across all CLI commands.

---

## Running Tests

The test suite runs completely offline using local HTML fixtures:

```bash
pytest -v
```

Tests verify:
- Website adapter URL matching and registry lookup.
- Full archive parsing, chapter number extraction, and ordering.
- Deduplication of chapter URLs.
- Ad, script, iframe, and comment removal while keeping semantic tags.
- Empty chapter detection and error handling.
- EPUB 3 container, metadata, cover image, and TOC compliance.
- SQLite persistence, state transitions, and resume logic.
- HTTP session retries on server errors.
- CLI argument parsing and commands.

---

## Troubleshooting

- **Rate Limiting / HTTP 429**: Increase the request delay using `--delay 1.5` or `novel-scraper config --set request_delay=2.0`.
- **Interrupted Downloads**: If a download stopped unexpectedly, run `novel-scraper resume <URL>` to resume immediately.
- **Custom EPUB Location**: Use `--output <path>` to save the generated file to an arbitrary location.
