"""Configuration manager for NovelScraper."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "novel-scraper"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"


@dataclass
class Config:
    """Application configuration settings."""

    request_timeout: float = 20.0
    request_delay: float = 0.5
    max_retries: int = 3
    backoff_factor: float = 1.5
    user_agent: str = DEFAULT_USER_AGENT
    download_dir: str = "downloads"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Instantiate Config from dictionary with type safety."""
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self)


def get_config_path(custom_path: Optional[str] = None) -> Path:
    """Return the active configuration path."""
    if custom_path:
        return Path(custom_path)
    env_path = os.getenv("NOVEL_SCRAPER_CONFIG")
    if env_path:
        return Path(env_path)
    return DEFAULT_CONFIG_FILE


def load_config(custom_path: Optional[str] = None) -> Config:
    """Load configuration from disk, falling back to defaults."""
    config_file = get_config_path(custom_path)
    if config_file.is_file():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Config.from_dict(data)
        except Exception:
            return Config()
    return Config()


def save_config(config: Config, custom_path: Optional[str] = None) -> Path:
    """Save configuration to disk."""
    config_file = get_config_path(custom_path)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2)
    return config_file
