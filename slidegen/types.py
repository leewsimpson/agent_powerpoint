from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional


class ScriptOrigin(str, Enum):
    INITIAL = "initial"
    FIX = "fix"
    IMPROVEMENT = "improvement"


class ScriptStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"


class PipelineStage(str, Enum):
    INITIAL_GENERATION = "initial_generation"
    EXECUTE_SCRIPT = "execute_script"
    FIX_LOOP = "fix_loop"
    SCREENSHOT = "screenshot"
    SCORING = "scoring"
    IMPROVEMENT_LOOP = "improvement_loop"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True)
class ImageInput:
    name: str
    path: Path
    description: str


@dataclass(frozen=True)
class SlideRequest:
    prompt: str
    images: list[ImageInput]
    reference_image: Optional[Path] = None


@dataclass
class ScriptVersion:
    version_id: str
    origin: ScriptOrigin
    path: Path
    status: ScriptStatus
    parent_version_id: Optional[str] = None
    request_id: Optional[str] = None


@dataclass
class ExecutionResult:
    success: bool
    pptx_path: Optional[Path]
    stdout: str
    stderr: str
    return_code: Optional[int]
    duration_seconds: float


@dataclass
class ScoreBreakdown:
    completeness: float
    content_accuracy: float
    layout_match: float
    visual_quality: float
    aggregate: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "completeness": self.completeness,
            "content_accuracy": self.content_accuracy,
            "layout_match": self.layout_match,
            "visual_quality": self.visual_quality,
            "aggregate": self.aggregate,
        }


@dataclass
class IterationRecord:
    stage: PipelineStage
    script_version_id: str
    execution: ExecutionResult
    screenshot_path: Optional[Path] = None
    score: Optional[ScoreBreakdown] = None


@dataclass
class RunMetadata:
    run_id: str
    request: SlideRequest
    script_versions: list[ScriptVersion] = field(default_factory=list)
    iterations: list[IterationRecord] = field(default_factory=list)
    best_version_id: Optional[str] = None
    best_score: Optional[ScoreBreakdown] = None
    status: PipelineStage = PipelineStage.INITIAL_GENERATION

    def to_dict(self) -> Dict[str, object]:
        return {
            "run_id": self.run_id,
            "prompt": self.request.prompt,
            "images": [
                {"name": img.name, "path": str(img.path), "description": img.description}
                for img in self.request.images
            ],
            "reference_image": str(self.request.reference_image) if self.request.reference_image else None,
            "script_versions": [
                {
                    "version_id": v.version_id,
                    "origin": v.origin.value,
                    "path": str(v.path),
                    "status": v.status.value,
                    "parent_version_id": v.parent_version_id,
                    "request_id": v.request_id,
                }
                for v in self.script_versions
            ],
            "iterations": [
                {
                    "stage": record.stage.value,
                    "script_version_id": record.script_version_id,
                    "execution": {
                        "success": record.execution.success,
                        "pptx_path": str(record.execution.pptx_path)
                        if record.execution.pptx_path
                        else None,
                        "stdout": record.execution.stdout,
                        "stderr": record.execution.stderr,
                        "return_code": record.execution.return_code,
                        "duration_seconds": record.execution.duration_seconds,
                    },
                    "screenshot_path": str(record.screenshot_path) if record.screenshot_path else None,
                    "score": record.score.to_dict() if record.score else None,
                }
                for record in self.iterations
            ],
            "best_version_id": self.best_version_id,
            "best_score": self.best_score.to_dict() if self.best_score else None,
            "status": self.status.value,
        }
