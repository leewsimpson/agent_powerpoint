from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from .artifacts import ArtifactManager, RunPaths
from .config import Settings
from .execution import ExecutionEngine
from .logging_config import get_logger
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

logger = get_logger(__name__)


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

    def run(self, request: SlideRequest, run_paths: RunPaths) -> RunMetadata:
        logger.progress("Starting slide generation workflow")  # type: ignore[attr-defined]
        logger.info("Request prompt: %s", request.prompt[:100] + "..." if len(request.prompt) > 100 else request.prompt)
        logger.info("Number of images: %d", len(request.images))
        logger.info("Has reference image: %s", request.reference_image is not None)
        
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
        logger.progress("Generating initial script...")  # type: ignore[attr-defined]
        logger.info("Stage: INITIAL_GENERATION")

        generation = self._openai.generate_initial_script(request.prompt, stored_images)
        current_version = script_manager.create_version(
            content=generation.script,
            origin=ScriptOrigin.INITIAL,
            request_id=generation.request_id,
        )
        script_cache[current_version.version_id] = generation.script
        logger.info("Initial script created: %s (request_id: %s)", current_version.version_id, generation.request_id)
        logger.progress("Script generated: %s", current_version.version_id)  # type: ignore[attr-defined]

        execution = self._execute_script(
            stage=PipelineStage.EXECUTE_SCRIPT,
            execution_engine=execution_engine,
            script=current_version,
            image_map=image_map,
            metadata=metadata,
            run_paths=run_paths,
        )

        if not execution.success:
            logger.warning("Initial script execution failed, entering fix loop")
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
                logger.error("All script fix attempts failed. Last error: %s", error_details)
                logger.progress("X All script fix attempts failed. Last error:\n%s", error_details)  # type: ignore[attr-defined]
                return metadata
            latest_version = script_manager.get_latest()
            if latest_version is None:
                raise RuntimeError("Script manager did not return a version after successful fix")
            current_version = latest_version
            logger.info("Script successfully fixed: %s", current_version.version_id)

        self._handle_successful_iteration(
            run_paths=run_paths,
            metadata=metadata,
            script_version=current_version,
            execution=execution,
        )
        if metadata.best_score:
            logger.info("Initial score: %s/100", metadata.best_score.aggregate)
            logger.progress("Initial score: %.1f/100", metadata.best_score.aggregate)  # type: ignore[attr-defined]
        else:
            logger.warning("No score available for initial version")

        if metadata.best_score and metadata.best_score.aggregate >= self._settings.behavior.target_score_threshold:
            logger.info("Target score reached: %.1f >= %.1f", metadata.best_score.aggregate, self._settings.behavior.target_score_threshold)
            logger.progress("Target score reached! (%.1f >= %.1f)", metadata.best_score.aggregate, self._settings.behavior.target_score_threshold)  # type: ignore[attr-defined]
            metadata.status = PipelineStage.COMPLETE
            self._persist_metadata(run_paths, metadata)
            return metadata

        logger.info("Starting improvement loop (max %d iterations)", self._settings.behavior.max_improvement_iterations)
        logger.progress("Starting improvement iterations (max %d)...", self._settings.behavior.max_improvement_iterations)  # type: ignore[attr-defined]
        for iteration_index in range(1, self._settings.behavior.max_improvement_iterations + 1):
            logger.info("=" * 60)
            logger.info("Improvement iteration %d/%d", iteration_index, self._settings.behavior.max_improvement_iterations)
            logger.progress("Improvement iteration %d/%d...", iteration_index, self._settings.behavior.max_improvement_iterations)  # type: ignore[attr-defined]
            metadata.status = PipelineStage.IMPROVEMENT_LOOP
            self._persist_metadata(run_paths, metadata)
            
            # Get the previous iteration's screenshot to pass to the LLM
            previous_screenshot = None
            if metadata.iterations:
                last_iteration = metadata.iterations[-1]
                if last_iteration.screenshot_path:
                    previous_screenshot = last_iteration.screenshot_path
                    logger.info("Using previous screenshot for improvement: %s", previous_screenshot)
            
            improvement = self._openai.improve_script(
                prompt=request.prompt,
                images=stored_images,
                previous_script=script_cache[current_version.version_id],
                score_feedback=metadata.best_score,
                iteration_index=iteration_index,
                previous_screenshot=previous_screenshot,
            )
            improved_version = script_manager.create_version(
                content=improvement.script,
                origin=ScriptOrigin.IMPROVEMENT,
                parent_version_id=current_version.version_id,
                request_id=improvement.request_id,
            )
            script_cache[improved_version.version_id] = improvement.script
            logger.info("Improved script created: %s (request_id: %s)", improved_version.version_id, improvement.request_id)
            
            execution = self._execute_script(
                stage=PipelineStage.IMPROVEMENT_LOOP,
                execution_engine=execution_engine,
                script=improved_version,
                image_map=image_map,
                metadata=metadata,
                run_paths=run_paths,
            )
            if not execution.success:
                logger.warning("Improvement iteration %d failed, continuing to next iteration", iteration_index)
                continue
            current_version = improved_version
            self._handle_successful_iteration(
                run_paths=run_paths,
                metadata=metadata,
                script_version=current_version,
                execution=execution,
            )
            if metadata.iterations and metadata.iterations[-1].score:
                score = metadata.iterations[-1].score.aggregate
                logger.info("Iteration %d score: %.1f/100", iteration_index, score)
                logger.progress("Iteration %d score: %.1f/100", iteration_index, score)  # type: ignore[attr-defined]
            if metadata.best_score and metadata.best_score.aggregate >= self._settings.behavior.target_score_threshold:
                logger.info("Target score reached: %.1f >= %.1f", metadata.best_score.aggregate, self._settings.behavior.target_score_threshold)
                logger.progress("Target score reached! (%.1f >= %.1f)", metadata.best_score.aggregate, self._settings.behavior.target_score_threshold)  # type: ignore[attr-defined]
                break

        logger.info("Workflow complete")
        logger.progress("Workflow complete.")  # type: ignore[attr-defined]
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
        logger.info("Executing script: %s (stage: %s)", script.version_id, stage.value)
        execution = execution_engine.execute(script, image_map)
        metadata.iterations.append(
            IterationRecord(stage=stage, script_version_id=script.version_id, execution=execution)
        )
        self._persist_metadata(run_paths, metadata)
        
        if not execution.success:
            logger.error("Script execution failed for %s: %s", script.version_id, execution.stderr[:200] if execution.stderr else "Unknown error")
        else:
            logger.info("Script execution succeeded for %s", script.version_id)
        
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
        logger.info("Entering fix loop (max %d attempts)", attempts)
        execution: Optional[ExecutionResult] = None
        for attempt in range(1, attempts + 1):
            logger.info("Fix attempt %d/%d", attempt, attempts)
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
            logger.info("Fixed script created: %s (request_id: %s)", fixed_version.version_id, fix_result.request_id)
            
            execution = self._execute_script(
                stage=PipelineStage.FIX_LOOP,
                execution_engine=execution_engine,
                script=fixed_version,
                image_map=image_map,
                metadata=metadata,
                run_paths=run_paths,
            )
            if execution.success:
                logger.info("Fix successful on attempt %d", attempt)
                return execution
            last_script = fixed_version
            last_script_content = fix_result.script
        
        logger.error("All %d fix attempts failed", attempts)
        return execution

    def _handle_successful_iteration(
        self,
        run_paths: RunPaths,
        metadata: RunMetadata,
        script_version: ScriptVersion,
        execution: ExecutionResult,
    ) -> None:
        if not execution.pptx_path:
            logger.warning("No PPTX path in execution result")
            return
        
        logger.info("Handling successful iteration for %s", script_version.version_id)
        metadata.status = PipelineStage.SCREENSHOT
        self._persist_metadata(run_paths, metadata)

        screenshot_path = run_paths.outputs_dir / f"slide_{script_version.version_id}.png"
        try:
            logger.info("Capturing screenshot: %s", screenshot_path)
            self._screenshot_service.capture(execution.pptx_path, screenshot_path)
            metadata.iterations[-1].screenshot_path = screenshot_path
            logger.info("Screenshot captured successfully")
        except Exception as screenshot_error:  # pylint: disable=broad-except
            logger.error("Screenshot capture failed: %s", screenshot_error, exc_info=True)
            logger.progress("CRITICAL ERROR: Screenshot capture failed")  # type: ignore[attr-defined]
            logger.progress("Error: %s", screenshot_error)  # type: ignore[attr-defined]
            logger.progress("PPTX created at: %s", execution.pptx_path)  # type: ignore[attr-defined]
            raise RuntimeError(f"Screenshot capture failed: {screenshot_error}") from screenshot_error

        metadata.status = PipelineStage.SCORING
        self._persist_metadata(run_paths, metadata)
        logger.info("Scoring slide for %s", script_version.version_id)
        score = self._scoring_service.score(metadata.request, screenshot_path, metadata.request.reference_image)
        metadata.iterations[-1].score = score
        logger.info("Score: %.1f/100 (completeness=%.1f, content=%.1f, layout=%.1f, visual=%.1f)", 
                   score.aggregate, score.completeness, score.content_accuracy, 
                   score.layout_match, score.visual_quality)

        if not metadata.best_score or score.aggregate > metadata.best_score.aggregate:
            logger.info("New best score: %.1f/100 (previous: %.1f/100)", 
                       score.aggregate, 
                       metadata.best_score.aggregate if metadata.best_score else 0.0)
            metadata.best_score = score
            metadata.best_version_id = script_version.version_id

        self._persist_metadata(run_paths, metadata)

    def _persist_metadata(self, run_paths: RunPaths, metadata: RunMetadata) -> None:
        self._artifact_manager.write_metadata(run_paths, metadata)