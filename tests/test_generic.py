"""Tests for Generic Direct-URL Adapter."""

from bs4 import BeautifulSoup
import pytest

from novel_scraper.adapters import get_adapter
from novel_scraper.adapters.generic import GenericAdapter


def test_generic_adapter_can_handle():
    """Verify that GenericAdapter accepts any HTTP/HTTPS URL."""
    assert GenericAdapter.can_handle("https://some-novel-site.org/novel-1") is True
    assert GenericAdapter.can_handle("http://another-site.com/ch1") is True
    assert GenericAdapter.can_handle("ftp://not-http.com") is False


def test_generic_adapter_resolution_priority():
    """Verify that specific adapters are matched first before falling back to generic."""
    # NovelPing URL should resolve to NovelPingAdapter
    adapter = get_adapter("https://novelping.com/book/some-novel")
    assert adapter.name == "NovelPing"

    # Arbitrary URL should fall back to GenericAdapter
    generic_adapter = get_adapter("https://myrandomnovelsite.org/book/martial-arts/chapter-1")
    assert isinstance(generic_adapter, GenericAdapter)


def test_generic_adapter_metadata_and_chapters_from_html():
    """Verify metadata extraction and chapter discovery heuristics from HTML."""
    html = """
    <html>
        <head>
            <title>The Great Cultivator - Read Free</title>
            <meta name="author" content="Grandmaster Writer">
            <meta property="og:description" content="Epic cultivation tale.">
        </head>
        <body>
            <h1>The Great Cultivator</h1>
            <div class="chapters">
                <a href="/novel/the-great-cultivator/chapter-1">Chapter 1: The Mountain</a>
                <a href="/novel/the-great-cultivator/chapter-2">Chapter 2: The Cave</a>
                <a href="/novel/the-great-cultivator/chapter-3">Chapter 3: The Sword</a>
            </div>
        </body>
    </html>
    """
    adapter = GenericAdapter()
    metadata = adapter.parse_metadata_from_html(html, "https://testsite.com/novel/the-great-cultivator")
    assert "The Great Cultivator" in metadata.title
    assert metadata.author == "Grandmaster Writer"
    assert metadata.description == "Epic cultivation tale."

    chapters = adapter.parse_chapters_from_html(html, "https://testsite.com/novel/the-great-cultivator")
    assert len(chapters) == 3
    assert chapters[0].title == "Chapter 1: The Mountain"
    assert chapters[0].chapter_number == 1.0
    assert chapters[1].url == "https://testsite.com/novel/the-great-cultivator/chapter-2"
