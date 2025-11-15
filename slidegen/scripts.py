from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .artifacts import ArtifactManager, RunPaths
from .types import RunMetadata, ScriptOrigin, ScriptStatus, ScriptVersion


@dataclass
class ScriptRecord:
    version: ScriptVersion
    content: str


class ScriptManager:
    def __init__(self, artifact_manager: ArtifactManager, run_paths: RunPaths, metadata: RunMetadata) -> None:
        self._artifact_manager = artifact_manager
        self._run_paths = run_paths
        self._metadata = metadata
        self._ordinal = 0

    def _next_version_id(self, origin: ScriptOrigin) -> str:
        self._ordinal += 1
        return f"v{self._ordinal}_{origin.value}"

    def create_version(
        self,
        content: str,
        origin: ScriptOrigin,
        parent_version_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> ScriptVersion:
        version_id = self._next_version_id(origin)
        script_path = self._artifact_manager.persist_script(self._run_paths, version_id, content)
        version = ScriptVersion(
            version_id=version_id,
            origin=origin,
            path=script_path,
            status=ScriptStatus.PENDING,
            parent_version_id=parent_version_id,
            request_id=request_id,
        )
        self._metadata.script_versions.append(version)
        return version

    def update_status(self, version: ScriptVersion, status: ScriptStatus) -> ScriptVersion:
        version.status = status
        return version

    def get_latest(self) -> Optional[ScriptVersion]:
        if not self._metadata.script_versions:
            return None
        return self._metadata.script_versions[-1]
