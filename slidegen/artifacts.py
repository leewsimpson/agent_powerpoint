from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .types import ImageInput, RunMetadata


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    base_dir: Path
    input_dir: Path
    scripts_dir: Path
    outputs_dir: Path
    logs_dir: Path


class ArtifactManager:
    def __init__(self, base_output_dir: Path) -> None:
        self._base_output_dir = base_output_dir
        self._base_output_dir.mkdir(parents=True, exist_ok=True)

    def create_run(self, run_id: Optional[str] = None) -> RunPaths:
        run_identifier = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        base_dir = self._base_output_dir / run_identifier
        input_dir = base_dir / "input"
        scripts_dir = base_dir / "scripts"
        outputs_dir = base_dir / "outputs"
        logs_dir = base_dir / "logs"
        for directory in (input_dir, scripts_dir, outputs_dir, logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return RunPaths(
            run_id=run_identifier,
            base_dir=base_dir,
            input_dir=input_dir,
            scripts_dir=scripts_dir,
            outputs_dir=outputs_dir,
            logs_dir=logs_dir,
        )

    def persist_prompt(self, run_paths: RunPaths, prompt: str) -> Path:
        prompt_path = run_paths.input_dir / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        return prompt_path

    def store_reference_image(self, run_paths: RunPaths, reference_image: Optional[Path]) -> Optional[Path]:
        if not reference_image:
            return None
        target = run_paths.input_dir / reference_image.name
        shutil.copy2(reference_image, target)
        return target

    def store_images(self, run_paths: RunPaths, images: Iterable[ImageInput]) -> Iterable[ImageInput]:
        stored = []
        for image in images:
            target = run_paths.input_dir / image.path.name
            if image.path != target:
                shutil.copy2(image.path, target)
            stored.append(ImageInput(name=image.name, path=target, description=image.description))
        return stored

    def write_metadata(self, run_paths: RunPaths, metadata: RunMetadata) -> Path:
        metadata_path = run_paths.base_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")
        return metadata_path

    def persist_script(self, run_paths: RunPaths, version_id: str, content: str) -> Path:
        filename = f"script_{version_id}.py"
        script_path = run_paths.scripts_dir / filename
        script_path.write_text(content, encoding="utf-8")
        return script_path

    def persist_execution_logs(self, run_paths: RunPaths, version_id: str, stdout: str, stderr: str) -> None:
        stdout_path = run_paths.logs_dir / f"{version_id}_stdout.log"
        stderr_path = run_paths.logs_dir / f"{version_id}_stderr.log"
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")

    def persist_score(self, run_paths: RunPaths, version_id: str, score: RunMetadata) -> Path:  # pragma: no cover - reserved for future usage
        # TODO: Store per-version score summaries; current metadata already captures this detail.
        return run_paths.base_dir / "metadata.json"
