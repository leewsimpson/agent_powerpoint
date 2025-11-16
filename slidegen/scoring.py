from __future__ import annotations

from pathlib import Path

from .config import ScoreWeights
from .openai_client import OpenAIClient
from .types import ScoreBreakdown, SlideRequest


class ScoringService:
    def __init__(self, weights: ScoreWeights, client: OpenAIClient) -> None:
        self._weights = weights
        self._client = client

    def score(self, request: SlideRequest, screenshot_path: Path, reference_image: Path | None) -> ScoreBreakdown:
        raw_score = self._client.score_slide(request.prompt, request.images, screenshot_path, reference_image)
        aggregate = (
            raw_score.completeness * self._weights.completeness
            + raw_score.content_accuracy * self._weights.content_accuracy
            + raw_score.layout_match * self._weights.layout_match
            + raw_score.visual_quality * self._weights.visual_quality
        ) / self._weights.total
        return ScoreBreakdown(
            completeness=raw_score.completeness,
            content_accuracy=raw_score.content_accuracy,
            layout_match=raw_score.layout_match,
            visual_quality=raw_score.visual_quality,
            aggregate=round(aggregate, 2),
            issues=raw_score.issues,  # Preserve issues from scoring
        )
