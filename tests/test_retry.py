"""Tests for HTTP retry behavior and network resilience."""

import io
from unittest.mock import patch
import pytest
import urllib3
import requests

from novel_scraper.config import Config
from novel_scraper.utils import create_session


def test_session_retry_on_status_500():
    """Verify that requests.Session retries on HTTP 500 status codes."""
    config = Config(max_retries=2, backoff_factor=0.01)
    session = create_session(config)

    call_count = 0

    def mock_make_request(self, conn, method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        return urllib3.response.HTTPResponse(
            body=io.BytesIO(b"Server Error"),
            status=500,
            reason="Internal Server Error",
            preload_content=False,
        )

    with patch.object(urllib3.connectionpool.HTTPConnectionPool, "_make_request", mock_make_request):
        resp = session.get("http://example.com/test-retry")
        assert call_count == 3
        assert resp.status_code == 500
