"""Tests for EPUB 3 generation, metadata, table of contents, and file validation."""

from pathlib import Path
import pytest
import zipfile

from novel_scraper.epub_builder import EpubBuilder
from novel_scraper.exceptions import EpubGenerationError
from novel_scraper.models import ChapterRecord, DownloadStatus, NovelMetadata


def test_epub_generation(tmp_path: Path):
    """Test generating a compliant EPUB 3 file."""
    metadata = NovelMetadata(
        title="Sample Novel Title",
        source_url="https://example.com/sample-novel",
        author="Famous Author",
        description="A great novel about adventures.",
        genres=["Fantasy", "Action"],
        novel_id="sample-novel",
    )

    chapters = [
        ChapterRecord(
            id=1,
            novel_id="sample-novel",
            order_index=1,
            chapter_number=1.0,
            title="Chapter 1: The Beginning",
            url="https://example.com/sample-novel/chapter-1",
            status=DownloadStatus.COMPLETED,
            content_html="<p>The journey begins in a small quiet town.</p><p>Second paragraph.</p>",
        ),
        ChapterRecord(
            id=2,
            novel_id="sample-novel",
            order_index=2,
            chapter_number=2.0,
            title="Chapter 2: The Departure",
            url="https://example.com/sample-novel/chapter-2",
            status=DownloadStatus.COMPLETED,
            content_html="<p>Ye Chen leaves the town with determination.</p>",
        ),
    ]

    builder = EpubBuilder()
    output_epub = tmp_path / "sample_novel.epub"
    result_path = builder.build_epub(metadata=metadata, chapters=chapters, output_path=output_epub)

    assert result_path == output_epub
    assert result_path.is_file()
    assert result_path.stat().st_size > 1000

    # Validate EPUB contents
    with zipfile.ZipFile(result_path, "r") as zf:
        namelist = zf.namelist()
        assert "mimetype" in namelist
        assert any("container.xml" in name for name in namelist)
        assert any("style.css" in name for name in namelist)
        assert any("chapter_00001.xhtml" in name for name in namelist)
        assert any("chapter_00002.xhtml" in name for name in namelist)

        # Check content of chapter file
        ch1_xml = [name for name in namelist if "chapter_00001.xhtml" in name][0]
        with zf.open(ch1_xml) as ch1_f:
            content = ch1_f.read().decode("utf-8")
            assert "The journey begins in a small quiet town." in content
            assert "Chapter 1: The Beginning" in content


def test_empty_chapters_epub_generation(tmp_path: Path):
    """Test that attempting to build an EPUB with no chapters raises EpubGenerationError."""
    metadata = NovelMetadata(
        title="Empty Novel",
        source_url="https://example.com/empty",
    )
    builder = EpubBuilder()
    output_path = tmp_path / "empty.epub"
    with pytest.raises(EpubGenerationError):
        builder.build_epub(metadata, [], output_path=output_path)
