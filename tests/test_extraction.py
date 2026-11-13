"""Tests for HTML content extraction, noise removal, and error handling."""

from pathlib import Path
import pytest

from novel_scraper.content_extractor import ContentExtractor
from novel_scraper.exceptions import ChapterExtractionError

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_html_content_extraction_from_fixture():
    """Verify that chapter 1 text is extracted cleanly from fixture."""
    fixture_path = FIXTURES_DIR / "novelping_chapter_1.html"
    assert fixture_path.exists(), "novelping_chapter_1.html fixture missing"

    with open(fixture_path, "r", encoding="utf-8") as f:
        raw_html = f.read()

    extractor = ContentExtractor(base_url="https://novelping.com")
    clean_xhtml, paragraphs = extractor.clean(raw_html, container_selector="#chr-content")

    assert len(paragraphs) > 40
    assert "My name is Ye Chen" in paragraphs[0]
    assert "<script" not in clean_xhtml.lower()
    assert "<style" not in clean_xhtml.lower()
    assert "<button" not in clean_xhtml.lower()
    assert "<form" not in clean_xhtml.lower()
    assert "<p>" in clean_xhtml


def test_ad_and_script_noise_removal():
    """Verify that ads, social shares, scripts, and navigation are removed while formatting is kept."""
    html_with_noise = """
    <div id="chr-content">
        <script>alert('malicious')</script>
        <div class="banner-ad">Advertisement text here</div>
        <p>This is the <strong>first</strong> paragraph with <em>emphasis</em> and a <br/> break.</p>
        <div class="social-share">Share on Facebook</div>
        <button class="btn btn-default">Click me</button>
        <p>This is the <b>second</b> paragraph.</p>
        <div id="comment-box">Leave a comment</div>
    </div>
    """
    extractor = ContentExtractor()
    clean_xhtml, paragraphs = extractor.clean(html_with_noise, container_selector="#chr-content")

    assert len(paragraphs) == 2
    assert paragraphs[0] == "This is the first paragraph with emphasis and a break."
    assert paragraphs[1] == "This is the second paragraph."

    assert "alert" not in clean_xhtml
    assert "Advertisement" not in clean_xhtml
    assert "Share on Facebook" not in clean_xhtml
    assert "Leave a comment" not in clean_xhtml
    assert "<strong>first</strong>" in clean_xhtml
    assert "<em>emphasis</em>" in clean_xhtml
    assert "<b>second</b>" in clean_xhtml


def test_empty_chapter_handling():
    """Verify ChapterExtractionError is raised for empty or whitespace-only content."""
    extractor = ContentExtractor()

    # Completely empty HTML
    with pytest.raises(ChapterExtractionError):
        extractor.clean("")

    # Container exists but contains only empty paragraphs or scripts
    empty_container_html = """
    <div id="chr-content">
        <script>console.log('empty')</script>
        <p>   </p>
    </div>
    """
    with pytest.raises(ChapterExtractionError):
        extractor.clean(empty_container_html, container_selector="#chr-content")


def test_missing_container_fallback():
    """Verify fallback container discovery when primary selector is missing."""
    html_without_selector = """
    <html>
        <body>
            <article>
                <p>Paragraph inside article tag without standard id.</p>
            </article>
        </body>
    </html>
    """
    extractor = ContentExtractor()
    clean_xhtml, paragraphs = extractor.clean(html_without_selector, container_selector="#missing-id")

    assert len(paragraphs) == 1
    assert "Paragraph inside article tag" in paragraphs[0]
