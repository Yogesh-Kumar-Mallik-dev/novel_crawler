"""Base adapter interface and adapter registry."""

from abc import ABC, abstractmethod
from typing import Optional, Type
import requests

from novel_scraper.config import Config
from novel_scraper.exceptions import UnsupportedWebsiteError
from novel_scraper.models import ChapterContent, ChapterInfo, NovelMetadata
from novel_scraper.utils import create_session

_ADAPTER_REGISTRY: list[Type["BaseAdapter"]] = []


def register_adapter(adapter_cls: Type["BaseAdapter"]) -> Type["BaseAdapter"]:
    """Decorator to register a website adapter."""
    if adapter_cls not in _ADAPTER_REGISTRY:
        _ADAPTER_REGISTRY.append(adapter_cls)
    return adapter_cls


def get_adapter(
    url: str,
    session: Optional[requests.Session] = None,
    config: Optional[Config] = None,
) -> "BaseAdapter":
    """Find and return an instantiated adapter capable of handling the URL.

    Raises:
        UnsupportedWebsiteError if no adapter can handle the given URL.
    """
    for adapter_cls in _ADAPTER_REGISTRY:
        if adapter_cls.can_handle(url):
            return adapter_cls(session=session, config=config)
    raise UnsupportedWebsiteError(f"No adapter available for URL: {url}")


def get_all_adapters() -> list[Type["BaseAdapter"]]:
    """Return all registered adapter classes."""
    return list(_ADAPTER_REGISTRY)


class BaseAdapter(ABC):
    """Abstract base class for website-specific scrapers."""

    name: str = "Base Adapter"
    domain: str = ""

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        config: Optional[Config] = None,
    ):
        self.config = config or Config()
        self.session = session or create_session(self.config)

    @classmethod
    @abstractmethod
    def can_handle(cls, url: str) -> bool:
        """Return True if this adapter supports the given URL."""

    @abstractmethod
    def get_novel_metadata(self, url: str) -> NovelMetadata:
        """Fetch and parse metadata for the novel."""

    @abstractmethod
    def discover_chapters(self, url: str) -> list[ChapterInfo]:
        """Discover all chapters available for the novel in chronological order."""

    @abstractmethod
    def extract_chapter(self, url: str) -> ChapterContent:
        """Fetch and extract clean content for a single chapter."""
