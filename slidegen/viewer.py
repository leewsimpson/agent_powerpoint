from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Optional

from .config import ViewerConfig


class ViewerLauncher:
    def __init__(self, config: ViewerConfig) -> None:
        self._config = config

    def launch(self, pptx_path: Path) -> Optional[subprocess.Popen]:
        command = self._resolve_command()
        if not command:
            return None
        expanded_command = command.format(pptx=str(pptx_path))
        try:
            return subprocess.Popen(expanded_command, shell=True)  # noqa: S602 - deliberate shell usage for command templating
        except Exception:  # pylint: disable=broad-except
            return None

    def close(self, process: Optional[subprocess.Popen]) -> None:
        if process and process.poll() is None:
            try:
                process.terminate()
            except Exception:  # pylint: disable=broad-except
                pass

    def _resolve_command(self) -> Optional[str]:
        system = platform.system().lower()
        if "windows" in system:
            return self._config.viewer_command_windows
        if "darwin" in system or "mac" in system:
            return self._config.viewer_command_macos
        return None
