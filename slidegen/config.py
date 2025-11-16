from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from dotenv import dotenv_values


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: Optional[str]
    default_model: str
    vision_model: str
    mock_mode: bool
    reasoning_effort: str  # "low", "medium", "high", or "minimal"


@dataclass(frozen=True)
class BehaviorConfig:
    max_script_retries: int
    max_improvement_iterations: int
    execution_timeout_seconds: int
    target_score_threshold: float


@dataclass(frozen=True)
class IOConfig:
    default_output_dir: Path
    workspace_dir: Path

@dataclass(frozen=True)
class ScoreWeights:
    completeness: float
    content_accuracy: float
    layout_match: float
    visual_quality: float

    @property
    def total(self) -> float:
        return self.completeness + self.content_accuracy + self.layout_match + self.visual_quality


@dataclass(frozen=True)
class Settings:
    openai: OpenAIConfig
    behavior: BehaviorConfig
    io: IOConfig
    score_weights: ScoreWeights


def _load_environment(env_path: Optional[Path]) -> Dict[str, str]:
    env_values: Dict[str, str] = {}
    if env_path and env_path.exists():
        env_values.update({k: v for k, v in dotenv_values(env_path).items() if v is not None})
    env_values.update({k: v for k, v in os.environ.items() if isinstance(v, str)})
    return env_values


def _to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(
    env_path: Optional[Path] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> Settings:
    """Load settings from .env file and environment variables."""

    base_dir = Path.cwd()
    env_data = _load_environment(env_path or base_dir / ".env")
    if overrides:
        env_data.update(overrides)

    workspace_dir = Path(env_data.get("WORKSPACE_DIR", base_dir))
    default_output_dir = Path(env_data.get("DEFAULT_OUTPUT_DIR", workspace_dir / "runs"))

    api_key = env_data.get("OPENAI_API_KEY")
    mock_mode = _to_bool(env_data.get("OPENAI_USE_MOCK"), default=api_key is None)
    if not mock_mode and not api_key:
        raise ValueError("OPENAI_API_KEY is required when OPENAI_USE_MOCK is false")

    openai = OpenAIConfig(
        api_key=api_key,
        default_model=env_data.get("OPENAI_DEFAULT_MODEL", "gpt-4o-mini"),
        vision_model=env_data.get("OPENAI_VISION_MODEL", "gpt-4o-mini"),
        mock_mode=mock_mode,
        reasoning_effort=env_data.get("OPENAI_REASONING_EFFORT", "medium"),
    )

    behavior = BehaviorConfig(
        max_script_retries=int(env_data.get("MAX_SCRIPT_RETRIES", "3")),
        max_improvement_iterations=int(env_data.get("MAX_IMPROVEMENT_ITERATIONS", "2")),
        execution_timeout_seconds=int(env_data.get("EXECUTION_TIMEOUT_SECONDS", "120")),
        target_score_threshold=float(env_data.get("TARGET_SCORE_THRESHOLD", "80")),
    )

    io_config = IOConfig(
        default_output_dir=default_output_dir,
        workspace_dir=workspace_dir,
    )

    score_weights = ScoreWeights(
        completeness=float(env_data.get("SCORE_WEIGHT_COMPLETENESS", "0.3")),
        content_accuracy=float(env_data.get("SCORE_WEIGHT_CONTENT_ACCURACY", "0.3")),
        layout_match=float(env_data.get("SCORE_WEIGHT_LAYOUT_MATCH", "0.25")),
        visual_quality=float(env_data.get("SCORE_WEIGHT_VISUAL_QUALITY", "0.15")),
    )

    total_weight = score_weights.total
    if not 0.99 <= total_weight <= 1.01:  # allow minor float drift
        raise ValueError("Score weights must sum to 1.0")
    default_output_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        openai=openai,
        behavior=behavior,
        io=io_config,
        score_weights=score_weights
    )
