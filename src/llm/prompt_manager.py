"""Prompt template loading, rendering, and management.

Prompt templates are stored as YAML files in config/prompts/.
Each template has a system_prompt and user_prompt section with
Jinja2-style template variables.
"""

import logging
import os
from pathlib import Path
from string import Template
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class PromptManager:
    """Loads and renders prompt templates for each generation stage."""

    DEFAULT_PROMPTS_DIR = Path(__file__).parent.parent.parent / "config" / "prompts"

    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = Path(prompts_dir) if prompts_dir else self.DEFAULT_PROMPTS_DIR
        self._cache: dict[str, dict] = {}

    def load(self, name: str) -> dict:
        """Load a prompt template by name (without .yaml extension)."""
        if name in self._cache:
            return self._cache[name]

        path = self.prompts_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            template = yaml.safe_load(f)

        self._cache[name] = template
        logger.debug("Loaded prompt template: %s", name)
        return template

    def render_system(self, name: str, **variables) -> str:
        """Render the system prompt of a template with variables."""
        template = self.load(name)
        raw = template.get("system", "")
        return self._substitute(raw, variables)

    def render_user(self, name: str, **variables) -> str:
        """Render the user prompt of a template with variables."""
        template = self.load(name)
        raw = template.get("user", "")
        return self._substitute(raw, variables)

    def render_both(self, name: str, **variables) -> tuple[str, str]:
        """Render both system and user prompts. Returns (system, user)."""
        return (
            self.render_system(name, **variables),
            self.render_user(name, **variables),
        )

    def invalidate_cache(self, name: Optional[str] = None) -> None:
        """Clear the template cache. If name is None, clears all."""
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()

    @staticmethod
    def _substitute(template_str: str, variables: dict) -> str:
        """Substitute variables into a template string.

        Uses Python's string.Template for safe substitution.
        Variables not provided are left as-is for downstream handling.
        """
        try:
            tmpl = Template(template_str)
            return tmpl.safe_substitute(**variables)
        except (KeyError, ValueError) as e:
            logger.warning("Template substitution issue: %s", e)
            return template_str
