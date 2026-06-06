"""Application configuration loaded from YAML files and environment variables."""

import logging
import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class AppConfig:
    """Centralized application configuration.

    Loads from:
    1. config/settings.yaml — Main configuration
    2. config/genres.yaml — Genre definitions
    3. Environment variables (prefixed with NOVEL_ or standard names)
    4. .env file
    """

    BASE_DIR = Path(__file__).parent.parent  # F:/novel-writer-agent/

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            config_dir = self.BASE_DIR / "config"

        # Load .env from project root
        env_file = self.BASE_DIR / ".env"
        if env_file.exists():
            load_dotenv(env_file)

        # Load settings
        settings_path = config_dir / "settings.yaml"
        with open(settings_path, "r", encoding="utf-8") as f:
            self._settings: dict = yaml.safe_load(f)

        # Load genres
        genres_path = config_dir / "genres.yaml"
        with open(genres_path, "r", encoding="utf-8") as f:
            self._genres: dict = yaml.safe_load(f)

        # Apply environment overrides
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to settings."""
        overrides = {
            "ANTHROPIC_API_KEY": ("llm", "api_key"),
            "DATABASE_URL": ("storage", "db_url"),
            "NOVEL_MORNING_TIME": ("scheduling", "morning_chapter"),
            "NOVEL_EVENING_TIME": ("scheduling", "evening_chapter"),
            "NOVEL_MONTHLY_BUDGET": ("budget", "monthly_limit_usd"),
        }

        for env_key, (section, key) in overrides.items():
            value = os.environ.get(env_key)
            if value:
                if section not in self._settings:
                    self._settings[section] = {}
                # Convert numeric values
                if "budget" in section or "limit" in key:
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        pass
                self._settings[section][key] = value

    # ── Convenience accessors ──────────────────────────────

    @property
    def llm(self) -> dict:
        return self._settings.get("llm", {})

    @property
    def default_model(self) -> str:
        return self.llm.get("default_model", "claude-sonnet-4-6-20250514")

    def model_for(self, stage: str) -> str:
        """Get the recommended model for a specific generation stage."""
        models = self.llm.get("models", {})
        return models.get(stage, self.default_model)

    @property
    def generation(self) -> dict:
        return self._settings.get("generation", {})

    @property
    def chapter_config(self) -> dict:
        return self.generation.get("chapter", {})

    @property
    def novel_config(self) -> dict:
        return self.generation.get("novel", {})

    @property
    def context(self) -> dict:
        return self._settings.get("context", {})

    @property
    def scheduling(self) -> dict:
        return self._settings.get("scheduling", {})

    @property
    def scraping(self) -> dict:
        return self._settings.get("scraping", {})

    @property
    def budget(self) -> dict:
        return self._settings.get("budget", {})

    @property
    def output(self) -> dict:
        return self._settings.get("output", {})

    @property
    def genres(self) -> list[dict]:
        """Get all genre definitions."""
        return self._genres.get("genres", {})

    @property
    def trending_tags_2025(self) -> list[str]:
        return self._genres.get("trending_tags_2025", [])

    @property
    def db_url(self) -> str:
        """Get database URL from settings or env."""
        storage = self._settings.get("storage", {})
        return storage.get("db_url",
               os.environ.get("DATABASE_URL",
               f"sqlite:///{self.BASE_DIR.as_posix()}/data/novels.db"))

    @property
    def output_dir(self) -> Path:
        out = self._settings.get("output", {}).get("dir")
        if out:
            return Path(out)
        return self.BASE_DIR / "output"

    @property
    def data_dir(self) -> Path:
        data = self._settings.get("data", {}).get("dir")
        if data:
            return Path(data)
        return self.BASE_DIR / "data"

    @property
    def log_dir(self) -> Path:
        logs = self._settings.get("logging", {}).get("dir")
        if logs:
            return Path(logs)
        return self.BASE_DIR / "logs"

    def to_dict(self) -> dict:
        """Get full settings dict (for debugging)."""
        return self._settings
