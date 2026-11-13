"""Tests for CLI arguments, parsing, and commands."""

from unittest.mock import MagicMock, patch
import pytest

from novel_scraper.cli import build_parser, handle_config, handle_sites
from novel_scraper.config import Config


def test_cli_parser_build():
    """Verify CLI parser builds with all required subcommands and flags."""
    parser = build_parser()

    # Test download command parsing
    args = parser.parse_args([
        "download",
        "https://novelping.com/book/journey-to-become-a-true-god",
        "--start-chapter", "1",
        "--end-chapter", "10",
        "--delay", "1.0",
        "--timeout", "15.0",
        "--force",
    ])
    assert args.command == "download"
    assert args.url == "https://novelping.com/book/journey-to-become-a-true-god"
    assert args.start_chapter == 1.0
    assert args.end_chapter == 10.0
    assert args.delay == 1.0
    assert args.timeout == 15.0
    assert args.force is True

    # Test resume command parsing
    args_resume = parser.parse_args([
        "resume",
        "https://novelping.com/book/journey-to-become-a-true-god",
    ])
    assert args_resume.command == "resume"
    assert args_resume.url == "https://novelping.com/book/journey-to-become-a-true-god"

    # Test chapters command parsing
    args_ch = parser.parse_args([
        "chapters",
        "https://novelping.com/book/journey-to-become-a-true-god",
        "--limit", "50",
    ])
    assert args_ch.command == "chapters"
    assert args_ch.limit == 50

    # Test epub command parsing
    args_ep = parser.parse_args([
        "epub",
        "https://novelping.com/book/journey-to-become-a-true-god",
        "--output", "test.epub",
    ])
    assert args_ep.command == "epub"
    assert args_ep.output == "test.epub"


def test_cli_sites_command(capsys):
    """Verify sites command lists supported adapters."""
    parser = build_parser()
    args = parser.parse_args(["sites"])
    ret = args.func(args, Config())
    assert ret == 0
    captured = capsys.readouterr()
    assert "NovelPing" in captured.out


def test_cli_config_command(capsys):
    """Verify config command displays and sets configuration."""
    cfg = Config(request_delay=0.5)
    parser = build_parser()
    args = parser.parse_args(["config"])
    ret = args.func(args, cfg)
    assert ret == 0
    captured = capsys.readouterr()
    assert "request_delay: 0.5" in captured.out


def test_direct_url_argv_handling():
    """Verify that passing a URL directly defaults to the download subcommand."""
    from novel_scraper.cli import main
    from unittest.mock import patch

    mock_download = MagicMock(return_value=0)
    with patch("novel_scraper.cli.handle_download", mock_download):
        with patch("sys.exit") as mock_exit:
            main(["https://example.com/novel/ch1", "--start-chapter", "1", "--end-chapter", "5"])
            mock_exit.assert_called_with(0)
            assert mock_download.called
            call_args = mock_download.call_args[0][0]
            assert call_args.url == "https://example.com/novel/ch1"
            assert call_args.start_chapter == 1.0
            assert call_args.end_chapter == 5.0
