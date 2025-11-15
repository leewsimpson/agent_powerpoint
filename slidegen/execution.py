from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict

from pptx import Presentation

from .artifacts import ArtifactManager, RunPaths
from .config import BehaviorConfig, RuntimeConfig
from .types import ExecutionResult, ScriptStatus, ScriptVersion


class ExecutionEngine:
    def __init__(
        self,
        artifact_manager: ArtifactManager,
        run_paths: RunPaths,
        behavior: BehaviorConfig,
        runtime: RuntimeConfig,
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_paths = run_paths
        self._behavior = behavior
        self._runtime = runtime

    def execute(self, script: ScriptVersion, image_map: Dict[str, Path]) -> ExecutionResult:
        output_path = self._run_paths.outputs_dir / f"slide_{script.version_id}.pptx"
        image_map_path = self._run_paths.input_dir / f"{script.version_id}_images.json"
        with image_map_path.open("w", encoding="utf-8") as handle:
            json.dump({name: str(path) for name, path in image_map.items()}, handle)

        command = self._build_command(script.path, output_path, image_map_path)
        
        # Log execution details
        exec_info = f"Executing script: {script.version_id}\n"
        exec_info += f"Command: {' '.join(str(c) for c in command)}\n"
        exec_info += f"Working directory: {self._run_paths.base_dir}\n"
        exec_info += f"Output path: {output_path}\n"
        exec_info += f"Image map: {image_map_path}\n"
        exec_info += "-" * 60 + "\n"

        start = time.perf_counter()
        stdout = exec_info
        stderr = ""
        return_code = None
        
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._behavior.execution_timeout_seconds,
                cwd=self._run_paths.base_dir,
                encoding="utf-8",
                errors="replace",
            )
            duration = time.perf_counter() - start
            stdout += completed.stdout or ""
            stderr = completed.stderr or ""
            return_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - start
            stdout += (exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout) or ""
            stderr = (exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr) or ""
            stderr += "\nExecution timed out"
            return_code = -1
        except Exception as exc:
            duration = time.perf_counter() - start
            stderr = f"Failed to execute script: {exc}"
            return_code = -1
        
        # Add execution summary to stdout
        stdout += f"\n{'-' * 60}\n"
        stdout += f"Execution completed in {duration:.2f}s\n"
        stdout += f"Return code: {return_code}\n"
        stdout += f"Output file exists: {output_path.exists()}\n"
        if output_path.exists():
            stdout += f"Output file size: {output_path.stat().st_size} bytes\n"

        self._artifact_manager.persist_execution_logs(self._run_paths, script.version_id, stdout, stderr)

        success = return_code == 0 and output_path.exists()
        
        # Add detailed error messages
        if return_code != 0:
            stderr += f"\n\nScript exited with code {return_code}"
        if not output_path.exists() and return_code == 0:
            stderr += f"\n\nScript completed but did not create output file: {output_path}"
        
        if success:
            try:
                self._validate_presentation(output_path)
            except Exception as validation_error:  # pylint: disable=broad-except
                success = False
                stderr += f"\n\nValidation error: {validation_error}"

        script.status = ScriptStatus.SUCCESS if success else ScriptStatus.FAILURE

        return ExecutionResult(
            success=success,
            pptx_path=output_path if success else None,
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
            duration_seconds=duration,
        )

    @staticmethod
    def _validate_presentation(pptx_path: Path) -> None:
        presentation = Presentation(pptx_path)
        if len(presentation.slides) == 0:
            raise ValueError("Presentation has no slides")

    def _build_command(self, script_path: Path, output_path: Path, image_map_path: Path) -> list[str]:
        if self._runtime.use_uv:
            uv_path = shutil.which(self._runtime.uv_executable)
            if uv_path:
                return [
                    uv_path,
                    "run",
                    "python",
                    str(script_path),
                    "--output",
                    str(output_path),
                    "--images",
                    str(image_map_path),
                ]
            if not self._runtime.allow_python_fallback:
                raise RuntimeError(
                    f"uv executable '{self._runtime.uv_executable}' not found and fallback disabled"
                )

        return [
            sys.executable,
            str(script_path),
            "--output",
            str(output_path),
            "--images",
            str(image_map_path),
        ]
