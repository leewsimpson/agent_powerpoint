from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from .artifacts import ArtifactManager
from .config import Settings, load_settings
from .logging_config import get_logger, setup_logging
from .openai_client import OpenAIClient
from .screenshot import ScreenshotService
from .scoring import ScoringService
from .state import SlideGenStateMachine
from .types import ImageInput, SlideRequest

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Python SlideGen orchestrator")
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="Inline prompt text (direct description)")
    prompt_group.add_argument("--prompt-file", type=Path, help="Path to a text or markdown file (.txt, .md) containing the prompt")

    parser.add_argument(
        "--image",
        action="append",
        dest="images",
        default=[],
        help="Image specification in the form name|/absolute/path|description",
    )
    parser.add_argument("--reference-image", type=Path, help="Optional reference layout image")
    parser.add_argument("--output-dir", type=Path, help="Override default output directory")
    parser.add_argument(
        "--mock-openai",
        action="store_true",
        help="Force mock mode for OpenAI even if an API key is configured",
    )
    parser.add_argument(
        "--real-openai",
        action="store_true",
        help="Force real OpenAI usage if an API key is available",
    )
    parser.add_argument("--run-id", help="Optional run identifier override")

    return parser.parse_args()


def load_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return args.prompt
    if args.prompt_file:
        return args.prompt_file.read_text(encoding="utf-8")
    raise ValueError("Prompt is required")


def parse_image_specs(values: List[str]) -> List[ImageInput]:
    images: List[ImageInput] = []
    for raw_value in values:
        parts = raw_value.split("|", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid image specification: {raw_value}")
        name, path_str, description = (part.strip() for part in parts)
        path = Path(path_str).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Image path not found: {path}")
        images.append(ImageInput(name=name, path=path, description=description))
    return images


def build_settings(args: argparse.Namespace) -> Settings:
    overrides: Dict[str, str] = {}
    if args.output_dir:
        overrides["DEFAULT_OUTPUT_DIR"] = str(args.output_dir.expanduser().resolve())
    if args.mock_openai and args.real_openai:
        raise ValueError("Cannot specify both --mock-openai and --real-openai")
    if args.mock_openai:
        overrides["OPENAI_USE_MOCK"] = "true"
    if args.real_openai:
        overrides["OPENAI_USE_MOCK"] = "false"
    return load_settings(overrides=overrides)


def create_state_machine(settings: Settings, artifact_manager: ArtifactManager) -> SlideGenStateMachine:
    openai_client = OpenAIClient(settings.openai)
    screenshot_service = ScreenshotService(settings.screenshot, settings.openai.mock_mode)
    scoring_service = ScoringService(settings.score_weights, openai_client)
    return SlideGenStateMachine(
        settings=settings,
        artifact_manager=artifact_manager,
        openai_client=openai_client,
        screenshot_service=screenshot_service,
        scoring_service=scoring_service,
    )


def run() -> None:
    args = parse_args()
    
    # Initial setup logging (console only) to show startup messages
    setup_logging(log_file_path=None)
    
    prompt = load_prompt(args)
    images = parse_image_specs(args.images)
    reference_image = args.reference_image.expanduser().resolve() if args.reference_image else None

    settings = build_settings(args)
    
    # Create run directory to get the log file path
    artifact_manager = ArtifactManager(settings.io.default_output_dir)
    run_paths = artifact_manager.create_run(run_id=args.run_id)
    
    # Now configure logging with the actual log file for this run
    log_file = run_paths.logs_dir / "run.log"
    setup_logging(log_file_path=log_file)
    
    logger.info("=" * 80)
    logger.info("Starting new SlideGen run")
    logger.info("Run ID: %s", run_paths.run_id)
    logger.info("Log file: %s", log_file)
    logger.info("=" * 80)
    logger.info("Configuration:")
    logger.info("  Mock mode: %s", settings.openai.mock_mode)
    logger.info("  Model: %s", settings.openai.default_model)
    logger.info("  Max retries: %s", settings.behavior.max_script_retries)
    logger.info("  Max improvements: %s", settings.behavior.max_improvement_iterations)
    logger.info("  Target score: %s", settings.behavior.target_score_threshold)
    logger.info("-" * 80)
    
    state_machine = create_state_machine(settings, artifact_manager)
    request = SlideRequest(prompt=prompt, images=images, reference_image=reference_image)
    
    try:
        metadata = state_machine.run(request, run_paths=run_paths)
    except Exception as error:
        logger.error("CRITICAL ERROR: %s", error, exc_info=True)
        logger.progress("X CRITICAL ERROR: %s", error)  # type: ignore[attr-defined]
        raise SystemExit(1) from error

    # Copy best PPTX to workspace root with timestamp
    workspace_pptx: Path | None = None
    if metadata.best_version_id:
        run_dir = settings.io.default_output_dir / metadata.run_id
        best_pptx = run_dir / "outputs" / f"slide_{metadata.best_version_id}.pptx"
        if best_pptx.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            workspace_pptx = settings.io.workspace_dir / f"slide_{timestamp}.pptx"
            shutil.copy2(best_pptx, workspace_pptx)
            logger.info("Best slide copied to workspace: %s", workspace_pptx)
            logger.progress("✓ Best slide saved to: %s", workspace_pptx.name)  # type: ignore[attr-defined]
            logger.progress("  Full path: %s", workspace_pptx)  # type: ignore[attr-defined]

    summary: Dict[str, object] = {
        "run_id": metadata.run_id,
        "best_version_id": metadata.best_version_id,
        "best_score": metadata.best_score.to_dict() if metadata.best_score else None,
        "status": metadata.status.value,
        "output_dir": str(settings.io.default_output_dir / metadata.run_id),
        "workspace_pptx": str(workspace_pptx) if workspace_pptx else None,
    }
    
    logger.info("Run summary: %s", json.dumps(summary, indent=2))
    logger.progress("\n%s", json.dumps(summary, indent=2))  # type: ignore[attr-defined]
    
    # Exit with error code if the workflow failed
    if metadata.status.value == "failed":
        logger.error("Workflow failed")
        logger.progress("X Workflow failed")  # type: ignore[attr-defined]
        
        # Show the last error details
        if metadata.iterations:
            last_iteration = metadata.iterations[-1]
            if last_iteration.execution and last_iteration.execution.stderr:
                logger.error("Last error: %s", last_iteration.execution.stderr)
                logger.progress("Error details:")  # type: ignore[attr-defined]
                logger.progress("%s", last_iteration.execution.stderr)  # type: ignore[attr-defined]
                logger.progress("Full logs in: %s/logs/", summary['output_dir'])  # type: ignore[attr-defined]
        
        raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    run()
