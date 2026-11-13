"""Custom exceptions for NovelScraper."""


class NovelScraperError(Exception):
    """Base exception for all novel-scraper errors."""


class UnsupportedWebsiteError(NovelScraperError):
    """Raised when no adapter is available to handle a given URL."""


class ChapterDiscoveryError(NovelScraperError):
    """Raised when chapters cannot be discovered from a website."""


class ChapterExtractionError(NovelScraperError):
    """Raised when a chapter's content or title cannot be extracted."""


class NetworkError(NovelScraperError):
    """Raised when an unrecoverable network or HTTP error occurs."""


class EpubGenerationError(NovelScraperError):
    """Raised when EPUB creation or packaging fails."""


class ConfigurationError(NovelScraperError):
    """Raised when configuration values are invalid."""


class DatabaseError(NovelScraperError):
    """Raised when a database operation fails."""
