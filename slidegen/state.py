from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

from .artifacts import ArtifactManager, RunPaths
from .config import Settings
from .execution import ExecutionEngine
from .openai_client import OpenAIClient
from .screenshot import ScreenshotService
from .scoring import ScoringService
from .scripts import ScriptManager
from .types import (
    ExecutionResult,
    ImageInput,
    IterationRecord,
    PipelineStage,
    RunMetadata,
    ScriptOrigin,
    ScriptVersion,
    SlideRequest,
)

logger = logging.getLogger(__name__)


def _log_user(message: str) -> None:
    """Print user-facing messages to console."""
    print(f"[SlideGen] {message}", flush=True)


class SlideGenStateMachine:
    def __init__(
        self,
        settings: Settings,
        artifact_manager: ArtifactManager,
        openai_client: OpenAIClient,
        screenshot_service: ScreenshotService,
        scoring_service: ScoringService,
    ) -> None:
        self._settings = settings
        self._artifact_manager = artifact_manager
        self._openai = openai_client
        self._screenshot_service = screenshot_service
        self._scoring_service = scoring_service

    def run(self, request: SlideRequest, run_id: Optional[str] = None) -> RunMetadata:
        _log_user(f"Starting new run: {run_id or 'auto-generated ID'}")
        run_paths = self._artifact_manager.create_run(run_id=run_id)
        _log_user(f"Run ID: {run_paths.run_id}")
        stored_images = list(self._artifact_manager.store_images(run_paths, request.images))
        reference_image = self._artifact_manager.store_reference_image(run_paths, request.reference_image)
        self._artifact_manager.persist_prompt(run_paths, request.prompt)

        stored_request = SlideRequest(prompt=request.prompt, images=stored_images, reference_image=reference_image)
        metadata = RunMetadata(run_id=run_paths.run_id, request=stored_request)
        script_manager = ScriptManager(self._artifact_manager, run_paths, metadata)
        execution_engine = ExecutionEngine(
            self._artifact_manager,
            run_paths,
            self._settings.behavior,
            self._settings.runtime,
        )
        image_map = {image.name: image.path for image in stored_images}
        script_cache: Dict[str, str] = {}

        metadata.status = PipelineStage.INITIAL_GENERATION
        self._persist_metadata(run_paths, metadata)
        _log_user("Generating initial script...")

        generation = self._openai.generate_initial_script(request.prompt, stored_images)
        current_version = script_manager.create_version(
            content=generation.script,
            origin=ScriptOrigin.INITIAL,
            request_id=generation.request_id,
        )
        script_cache[current_version.version_id] = generation.script
        _log_user(f"Script generated: {current_version.version_id}")

        execution = self._execute_script(
            stage=PipelineStage.EXECUTE_SCRIPT,
            execution_engine=execution_engine,
            script=current_version,
            image_map=image_map,
            metadata=metadata,
            run_paths=run_paths,
        )

        if not execution.success:
            execution = self._run_fix_loop(
                request=request,
                stored_images=stored_images,
                execution_engine=execution_engine,
                script_manager=script_manager,
                metadata=metadata,
                run_paths=run_paths,
                image_map=image_map,
                last_script=current_version,
                last_script_content=generation.script,
                script_cache=script_cache,
            )
            if not execution or not execution.success:
                metadata.status = PipelineStage.FAILED
                self._persist_metadata(run_paths, metadata)
                error_details = execution.stderr if execution and execution.stderr else "Unknown error"
                _log_user(f"X All script fix attempts failed. Last error:\n{error_details}")
                return metadata
            latest_version = script_manager.get_latest()
            if latest_version is None:
                raise RuntimeError("Script manager did not return a version after successful fix")
            current_version = latest_version

        self._handle_successful_iteration(
            run_paths=run_paths,
            metadata=metadata,
            script_version=current_version,
            execution=execution,
        )
        _log_user(f"Initial score: {metadata.best_score.aggregate:.1f}/100" if metadata.best_score else "Score unavailable")

        if metadata.best_score and metadata.best_score.aggregate >= self._settings.behavior.target_score_threshold:
            _log_user(f"Target score reached! ({metadata.best_score.aggregate:.1f} >= {self._settings.behavior.target_score_threshold})")
            metadata.status = PipelineStage.COMPLETE
            self._persist_metadata(run_paths, metadata)
            return metadata

        _log_user(f"Starting improvement iterations (max {self._settings.behavior.max_improvement_iterations})...")
        for iteration_index in range(1, self._settings.behavior.max_improvement_iterations + 1):
            _log_user(f"Improvement iteration {iteration_index}/{self._settings.behavior.max_improvement_iterations}...")
            metadata.status = PipelineStage.IMPROVEMENT_LOOP
            self._persist_metadata(run_paths, metadata)
            improvement = self._openai.improve_script(
                prompt=request.prompt,
                images=stored_images,
                previous_script=script_cache[current_version.version_id],
                score_feedback=metadata.best_score,
                iteration_index=iteration_index,
            )
            improved_version = script_manager.create_version(
                content=improvement.script,
                origin=ScriptOrigin.IMPROVEMENT,
                parent_version_id=current_version.version_id,
                request_id=improvement.request_id,
            )
            script_cache[improved_version.version_id] = improvement.script
            execution = self._execute_script(
                stage=PipelineStage.IMPROVEMENT_LOOP,
                execution_engine=execution_engine,
                script=improved_version,
                image_map=image_map,
                metadata=metadata,
                run_paths=run_paths,
            )
            if not execution.success:
                continue
            current_version = improved_version
            self._handle_successful_iteration(
                run_paths=run_paths,
                metadata=metadata,
                script_version=current_version,
                execution=execution,
            )
            if metadata.iterations and metadata.iterations[-1].score:
                _log_user(f"Iteration {iteration_index} score: {metadata.iterations[-1].score.aggregate:.1f}/100")
            if metadata.best_score and metadata.best_score.aggregate >= self._settings.behavior.target_score_threshold:
                _log_user(f"Target score reached! ({metadata.best_score.aggregate:.1f} >= {self._settings.behavior.target_score_threshold})")
                break

        _log_user("Workflow complete.")
        metadata.status = PipelineStage.COMPLETE
        self._persist_metadata(run_paths, metadata)
        return metadata

    def _execute_script(
        self,
        stage: PipelineStage,
        execution_engine: ExecutionEngine,
        script: ScriptVersion,
        image_map: Dict[str, Path],
        metadata: RunMetadata,
        run_paths: RunPaths,
    ) -> ExecutionResult:
        execution = execution_engine.execute(script, image_map)
        metadata.iterations.append(
            IterationRecord(stage=stage, script_version_id=script.version_id, execution=execution)
        )
        self._persist_metadata(run_paths, metadata)
        
        # Log execution errors for debugging
        if not execution.success and execution.stderr:
            logger.error("Script execution failed for %s:\\n%s", script.version_id, execution.stderr)
        
        return execution

    def _run_fix_loop(
        self,
        request: SlideRequest,
        stored_images: list[ImageInput],
        execution_engine: ExecutionEngine,
        script_manager: ScriptManager,
        metadata: RunMetadata,
        run_paths: RunPaths,
        image_map: Dict[str, Path],
        last_script: ScriptVersion,
        last_script_content: str,
        script_cache: Dict[str, str],
    ) -> Optional[ExecutionResult]:
        attempts = self._settings.behavior.max_script_retries
        execution: Optional[ExecutionResult] = None
        for attempt in range(1, attempts + 1):
            logger.info("Attempting script fix iteration %s", attempt)
            fix_result = self._openai.fix_script(
                prompt=request.prompt,
                images=stored_images,
                failing_script=last_script_content,
                error_log=execution.stderr if execution else "",
            )
            fixed_version = script_manager.create_version(
                content=fix_result.script,
                origin=ScriptOrigin.FIX,
                parent_version_id=last_script.version_id,
                request_id=fix_result.request_id,
            )
            script_cache[fixed_version.version_id] = fix_result.script
            execution = self._execute_script(
                stage=PipelineStage.FIX_LOOP,
                execution_engine=execution_engine,
                script=fixed_version,
                image_map=image_map,
                metadata=metadata,
                run_paths=run_paths,
            )
            if execution.success:
                return execution
            last_script = fixed_version
            last_script_content = fix_result.script
        return execution

    def _handle_successful_iteration(
        self,
        run_paths: RunPaths,
        metadata: RunMetadata,
        script_version: ScriptVersion,
        execution: ExecutionResult,
    ) -> None:
        if not execution.pptx_path:
            return
        metadata.status = PipelineStage.SCREENSHOT
        self._persist_metadata(run_paths, metadata)

        screenshot_path = run_paths.outputs_dir / f"slide_{script_version.version_id}.png"
        try:
            self._screenshot_service.capture(execution.pptx_path, screenshot_path)
            metadata.iterations[-1].screenshot_path = screenshot_path
        except Exception as screenshot_error:  # pylint: disable=broad-except
            logger.error("Screenshot capture failed: %s", screenshot_error)
            _log_user(f"CRITICAL ERROR: Screenshot capture failed")
            _log_user(f"Error: {screenshot_error}")
            _log_user(f"PPTX created at: {execution.pptx_path}")
            raise RuntimeError(f"Screenshot capture failed: {screenshot_error}") from screenshot_error

        metadata.status = PipelineStage.SCORING
        self._persist_metadata(run_paths, metadata)
        score = self._scoring_service.score(metadata.request, screenshot_path, metadata.request.reference_image)
        metadata.iterations[-1].score = score

        if not metadata.best_score or score.aggregate > metadata.best_score.aggregate:
            metadata.best_score = score
            metadata.best_version_id = script_version.version_id

        self._persist_metadata(run_paths, metadata)

    def _persist_metadata(self, run_paths: RunPaths, metadata: RunMetadata) -> None:
        self._artifact_manager.write_metadata(run_paths, metadata)