"""Website adapters module for NovelScraper."""

from novel_scraper.adapters.base import (
    BaseAdapter,
    get_adapter,
    get_all_adapters,
    register_adapter,
)
from novel_scraper.adapters.generic import GenericAdapter
from novel_scraper.adapters.novelping import NovelPingAdapter

__all__ = [
    "BaseAdapter",
    "GenericAdapter",
    "NovelPingAdapter",
    "get_adapter",
    "get_all_adapters",
    "register_adapter",
]
