from __future__ import annotations

from pathlib import Path
from typing import Dict


class PromptStore:
    """Load and format reusable prompt templates from disk."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or Path(__file__).resolve().parent / "prompt_templates"
        if not self._base_dir.exists():
            raise FileNotFoundError(f"Prompt directory not found: {self._base_dir}")
        self._cache: Dict[str, str] = {}

    def get(self, name: str) -> str:
        template_name = self._normalize_name(name)
        if template_name not in self._cache:
            path = self._base_dir / f"{template_name}.txt"
            if not path.exists():
                raise FileNotFoundError(f"Prompt template missing: {path}")
            self._cache[template_name] = path.read_text(encoding="utf-8")
        return self._cache[template_name]

    def render(self, name: str, **context: object) -> str:
        template = self.get(name)
        # Auto-inject shared templates if referenced
        if "{shared_" in template:
            context = self._inject_shared_templates(context)
        return template.format(**context)
    
    def _inject_shared_templates(self, context: dict[str, object]) -> dict[str, object]:
        """Automatically inject shared template fragments."""
        shared_names = ["shared_requirements", "shared_structure", "shared_pptx_api"]
        result = dict(context)
        for shared_name in shared_names:
            if shared_name not in result:
                try:
                    result[shared_name] = self.get(shared_name)
                except FileNotFoundError:
                    # Shared template doesn't exist, skip it
                    pass
        return result

    @staticmethod
    def _normalize_name(name: str) -> str:
        return name.replace(".txt", "").strip()
