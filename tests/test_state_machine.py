from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from slidegen.artifacts import ArtifactManager
from slidegen.config import load_settings
from slidegen.openai_client import OpenAIClient
from slidegen.scoring import ScoringService
from slidegen.screenshot import ScreenshotService
from slidegen.state import SlideGenStateMachine
from slidegen.types import ImageInput, PipelineStage, SlideRequest
from slidegen.viewer import ViewerLauncher


def _create_sample_image(path: Path) -> None:
    image = Image.new("RGB", (100, 100), color=(255, 0, 0))
    image.save(path)


def test_state_machine_end_to_end(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_USE_MOCK", "true")
    monkeypatch.setenv("DEFAULT_OUTPUT_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("MAX_IMPROVEMENT_ITERATIONS", "1")
    monkeypatch.setenv("USE_UV", "false")

    settings = load_settings()

    image_path = tmp_path / "logo.png"
    _create_sample_image(image_path)

    request = SlideRequest(
        prompt="Sample Slide\nKey point one\nKey point two",
        images=[ImageInput(name="logo", path=image_path, description="Company logo in the corner")],
        reference_image=None,
    )

    artifact_manager = ArtifactManager(settings.io.default_output_dir)
    openai_client = OpenAIClient(settings.openai)
    viewer = ViewerLauncher(settings.viewer)
    screenshot_service = ScreenshotService(settings.screenshot, viewer, settings.openai.mock_mode)
    scoring_service = ScoringService(settings.score_weights, openai_client)
    state_machine = SlideGenStateMachine(
        settings=settings,
        artifact_manager=artifact_manager,
        openai_client=openai_client,
        screenshot_service=screenshot_service,
        scoring_service=scoring_service,
    )

    run_identifier = "custom-run"
    metadata = state_machine.run(request, run_id=run_identifier)

    assert metadata.status == PipelineStage.COMPLETE
    assert metadata.run_id == run_identifier
    assert metadata.best_score is not None
    assert metadata.best_version_id is not None
    run_dir = settings.io.default_output_dir / metadata.run_id
    assert (run_dir / "outputs").exists()
    assert metadata.iterations
    # Ensure slide artifact exists
    assert any(path.name.endswith(".pptx") for path in (run_dir / "outputs").iterdir())
    assert any(path.name.endswith(".png") for path in (run_dir / "outputs").iterdir())
