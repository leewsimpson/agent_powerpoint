from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from .artifacts import ArtifactManager
from .config import Settings, load_settings
from .openai_client import OpenAIClient
from .screenshot import ScreenshotService
from .scoring import ScoringService
from .state import SlideGenStateMachine
from .types import ImageInput, SlideRequest
from .viewer import ViewerLauncher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Python SlideGen orchestrator")
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="Inline prompt text")
    prompt_group.add_argument("--prompt-file", type=Path, help="Path to a text file containing the prompt")

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
    parser.add_argument("--log-level", default="INFO", help="Python logging level (default: INFO)")
    parser.add_argument("--run-id", help="Optional run identifier override")

    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(levelname)s - %(message)s")


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


def create_state_machine(settings: Settings) -> SlideGenStateMachine:
    artifact_manager = ArtifactManager(settings.io.default_output_dir)
    openai_client = OpenAIClient(settings.openai)
    viewer = ViewerLauncher(settings.viewer)
    screenshot_service = ScreenshotService(settings.screenshot, viewer, settings.openai.mock_mode)
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
    configure_logging(args.log_level)

    prompt = load_prompt(args)
    images = parse_image_specs(args.images)
    reference_image = args.reference_image.expanduser().resolve() if args.reference_image else None

    settings = build_settings(args)
    state_machine = create_state_machine(settings)
    request = SlideRequest(prompt=prompt, images=images, reference_image=reference_image)
    
    try:
        metadata = state_machine.run(request, run_id=args.run_id)
    except Exception as error:
        print(f"\n[SlideGen] X CRITICAL ERROR: {error}", flush=True)
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
            print(f"\n[SlideGen] ✓ Best slide saved to: {workspace_pptx.name}", flush=True)
            print(f"[SlideGen]   Full path: {workspace_pptx}", flush=True)

    summary: Dict[str, object] = {
        "run_id": metadata.run_id,
        "best_version_id": metadata.best_version_id,
        "best_score": metadata.best_score.to_dict() if metadata.best_score else None,
        "status": metadata.status.value,
        "output_dir": str(settings.io.default_output_dir / metadata.run_id),
        "workspace_pptx": str(workspace_pptx) if workspace_pptx else None,
    }
    print(f"\n{json.dumps(summary, indent=2)}")
    
    # Exit with error code if the workflow failed
    if metadata.status.value == "failed":
        print("\n[SlideGen] X Workflow failed", flush=True)
        
        # Show the last error details
        if metadata.iterations:
            last_iteration = metadata.iterations[-1]
            if last_iteration.execution and last_iteration.execution.stderr:
                print("\n[SlideGen] Error details:", flush=True)
                print(last_iteration.execution.stderr, flush=True)
                print(f"\n[SlideGen] Full logs in: {summary['output_dir']}/logs/", flush=True)
        
        raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    run()
