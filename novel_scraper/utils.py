"""Helper utilities for NovelScraper."""

import re
import urllib.parse
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from novel_scraper.config import Config


def sanitize_filename(name: str, max_length: int = 150) -> str:
    """Sanitize a string for use as a filesystem filename.

    Removes illegal characters, trims excessive whitespace, and truncates.
    """
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = re.sub(r"[\s_]+", " ", cleaned).strip()
    if not cleaned:
        cleaned = "novel"
    return cleaned[:max_length].strip()


def parse_chapter_number(text: str) -> Optional[float]:
    """Extract a chapter number from a title or URL fragment.

    Supports formats like:
    - 'Chapter 1' -> 1.0
    - 'Chapter 10.5' -> 10.5
    - 'Ch. 45: Title' -> 45.0
    - 'c12' -> 12.0
    - '100 - Title' -> 100.0
    Returns None if no numeric chapter indicator is found (e.g., 'Prologue').
    """
    patterns = [
        r"(?:chapter|chap|ch\.?|c)\s*(\d+(?:\.\d+)?)",
        r"\b(\d+(?:\.\d+)?)\s*(?:[-:–—]|\b)",
    ]

    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (ValueError, TypeError):
                continue
    return None


def normalize_url(url: str) -> str:
    """Normalize a URL by trimming fragments, query strings where appropriate, and trailing slashes."""
    parsed = urllib.parse.urlsplit(url.strip())
    # Ensure scheme is present
    scheme = parsed.scheme if parsed.scheme else "https"
    path = parsed.path.rstrip("/")
    normalized = urllib.parse.urlunsplit((scheme, parsed.netloc.lower(), path, parsed.query, ""))
    return normalized


def create_session(config: Config) -> requests.Session:
    """Create a configured requests.Session with retries and standard headers."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": config.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    retry_strategy = Retry(
        total=config.max_retries,
        backoff_factor=config.backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
