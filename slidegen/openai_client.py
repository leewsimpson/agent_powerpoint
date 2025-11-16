from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from openai import OpenAI

from .config import OpenAIConfig
from .logging_config import get_logger, log_ai_request, log_ai_response
from .prompt_store import PromptStore
from .types import ImageInput, ScoreBreakdown

logger = get_logger(__name__)


@dataclass
class ScriptGenerationResult:
    script: str
    request_id: str
    prompt_payload: str


class OpenAIClient:
    """High level abstraction over LLM powered behaviors."""

    def __init__(self, config: OpenAIConfig, prompt_store: PromptStore | None = None) -> None:
        self._config = config
        self._prompt_store = prompt_store or PromptStore()
        self._client: Optional[OpenAI] = None
        if not config.mock_mode and config.api_key:
            self._client = OpenAI(api_key=config.api_key)

    def generate_initial_script(self, prompt: str, images: Iterable[ImageInput]) -> ScriptGenerationResult:
        image_list = list(images)
        prompt_payload = self._render_template(
            "initial_script",
            prompt=prompt,
            image_table=self._format_images(image_list),
        )
        
        log_ai_request(logger, "GENERATE INITIAL SCRIPT", prompt_payload, self._config.default_model)
        
        if self._config.mock_mode or not self._client:
            logger.info("Using mock mode for script generation")
            script = self._render_script(prompt, image_list, iteration_tag="initial")
            request_id = self._mock_request_id(prompt_payload)
        else:
            image_paths = [img.path for img in image_list]
            script, request_id = self._call_openai_with_vision(prompt_payload, image_paths)
        
        log_ai_response(logger, "GENERATE INITIAL SCRIPT", f"Generated {len(script)} characters of script code", request_id)
        return ScriptGenerationResult(script=script, request_id=request_id, prompt_payload=prompt_payload)

    def fix_script(
        self,
        prompt: str,
        images: Iterable[ImageInput],
        failing_script: str,
        error_log: str,
    ) -> ScriptGenerationResult:
        image_list = list(images)
        prompt_payload = self._render_template(
            "fix_script",
            prompt=prompt,
            image_table=self._format_images(image_list),
            failing_script=failing_script,
            error_log=error_log,
        )
        
        log_ai_request(logger, "FIX SCRIPT", prompt_payload, self._config.default_model)
        
        if self._config.mock_mode or not self._client:
            logger.info("Using mock mode for script fix")
            script = self._render_script(prompt, image_list, iteration_tag="fixed")
            request_id = self._mock_request_id(prompt_payload)
        else:
            image_paths = [img.path for img in image_list]
            script, request_id = self._call_openai_with_vision(prompt_payload, image_paths)
        
        log_ai_response(logger, "FIX SCRIPT", f"Generated {len(script)} characters of fixed script code", request_id)
        return ScriptGenerationResult(script=script, request_id=request_id, prompt_payload=prompt_payload)

    def improve_script(
        self,
        prompt: str,
        images: Iterable[ImageInput],
        previous_script: str,
        score_feedback: Optional[ScoreBreakdown],
        iteration_index: int,
        previous_screenshot: Optional[Path] = None,
    ) -> ScriptGenerationResult:
        iteration_tag = f"improved_{iteration_index}"
        image_list = list(images)
        prompt_payload = self._render_template(
            "improve_script",
            prompt=prompt,
            image_table=self._format_images(image_list),
            previous_script=previous_script,
            score_feedback=self._format_score(score_feedback),
            iteration_index=iteration_index,
            previous_screenshot=str(previous_screenshot) if previous_screenshot else "None (first iteration)",
        )
        
        log_ai_request(logger, f"IMPROVE SCRIPT (iteration {iteration_index})", prompt_payload, self._config.default_model)
        
        if self._config.mock_mode or not self._client:
            logger.info("Using mock mode for script improvement")
            script = self._render_script(prompt, image_list, iteration_tag=iteration_tag)
            request_id = self._mock_request_id(prompt_payload)
        else:
            image_paths = [img.path for img in image_list]
            if previous_screenshot and previous_screenshot.exists():
                image_paths.append(previous_screenshot)
            script, request_id = self._call_openai_with_vision(prompt_payload, image_paths)
        
        log_ai_response(logger, f"IMPROVE SCRIPT (iteration {iteration_index})", f"Generated {len(script)} characters of improved script code", request_id)
        return ScriptGenerationResult(script=script, request_id=request_id, prompt_payload=prompt_payload)

    def score_slide(
        self,
        prompt: str,
        images: Iterable[ImageInput],
        screenshot_path: Optional[Path],
        reference_image: Optional[Path],
    ) -> ScoreBreakdown:
        """Score a slide based on prompt, assets, and optionally a reference image.
        
        Currently uses deterministic pseudo-scoring. Can be extended to use Vision API.
        """

        image_list = list(images)
        prompt_payload = self._render_template(
            "score_slide",
            prompt=prompt,
            image_table=self._format_images(image_list),
            screenshot_path=str(screenshot_path) if screenshot_path else "None",
            reference_image=str(reference_image) if reference_image else "None",
        )

        # TODO: When ready to use real API, uncomment below and remove mock scoring
        # if not self._config.mock_mode and self._client:
        #     image_paths = [img.path for img in image_list]
        #     if screenshot_path and screenshot_path.exists():
        #         image_paths.append(screenshot_path)
        #     if reference_image and reference_image.exists():
        #         image_paths.append(reference_image)
        #     return self._call_openai_for_scoring(prompt_payload, image_paths)

        logger.info("Scoring slide (mock mode)")
        logger.debug("Score prompt payload: %s", prompt_payload[:200] + "..." if len(prompt_payload) > 200 else prompt_payload)

        prompt_weight = min(len(prompt) / 500.0, 1.0)
        template_weight = min(len(prompt_payload) / 2000.0, 1.0)
        image_bonus = min(len(image_list) * 0.05, 0.25)
        screenshot_bonus = 0.15 if screenshot_path and screenshot_path.exists() else 0.0
        reference_bonus = 0.05 if reference_image else 0.0

        completeness = 60.0 + 30.0 * prompt_weight + image_bonus * 100
        content_accuracy = 55.0 + 35.0 * template_weight
        layout_match = 50.0 + image_bonus * 80 + reference_bonus * 100
        visual_quality = 50.0 + screenshot_bonus * 100

        completeness = min(completeness, 95.0)
        content_accuracy = min(content_accuracy, 92.0)
        layout_match = min(layout_match, 90.0)
        visual_quality = min(visual_quality, 88.0)

        aggregate = (completeness + content_accuracy + layout_match + visual_quality) / 4

        breakdown = ScoreBreakdown(
            completeness=round(completeness, 2),
            content_accuracy=round(content_accuracy, 2),
            layout_match=round(layout_match, 2),
            visual_quality=round(visual_quality, 2),
            aggregate=round(aggregate, 2),
        )
        
        logger.info("Score breakdown: %s", breakdown.to_dict())
        return breakdown

    def _call_openai_with_vision(self, prompt_payload: str, image_paths: list[Path]) -> tuple[str, str]:
        """Call OpenAI Vision API with text prompt and images."""
        if not self._client:
            raise ValueError("OpenAI client not initialized")
        
        logger.info("Calling OpenAI Vision API with model: %s", self._config.default_model)
        logger.info("Number of images to send: %d", len(image_paths))
        
        try:
            # Build message content with text and images
            content: list[dict[str, object]] = [{"type": "text", "text": prompt_payload}]
            
            for image_path in image_paths:
                if image_path.exists():
                    logger.debug("Encoding image: %s", image_path)
                    base64_image = self._encode_image(image_path)
                    mime_type = self._get_image_mime_type(image_path)
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}",
                            "detail": "high"
                        }
                    })
                else:
                    logger.warning("Image path does not exist: %s", image_path)
            
            response = self._client.chat.completions.create(
                model=self._config.default_model,
                messages=[
                    {"role": "system", "content": "You are an expert Python developer. Return only executable Python code."},
                    {"role": "user", "content": content}  # type: ignore[typeddict-item]
                ],
                temperature=0.7,
                max_tokens=4096,
            )
            
            script = response.choices[0].message.content or ""
            request_id = response.id
            
            logger.info("OpenAI API call successful. Request ID: %s, Response length: %d chars", request_id, len(script))
            
            # Extract code from markdown code blocks if present
            script = self._extract_code_from_markdown(script)
            
            logger.info("Extracted code length: %d chars", len(script))
            return script, request_id
        except Exception as error:
            logger.error("OpenAI API call failed: %s", error, exc_info=True)
            raise
    
    @staticmethod
    def _encode_image(image_path: Path) -> str:
        """Encode image to base64 string."""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")
    
    @staticmethod
    def _get_image_mime_type(image_path: Path) -> str:
        """Get MIME type for image based on file extension."""
        ext = image_path.suffix.lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        return mime_types.get(ext, "image/png")  # Default to PNG
    
    @staticmethod
    def _extract_code_from_markdown(text: str) -> str:
        """Extract Python code from markdown code blocks."""
        lines = text.split("\n")
        in_code_block = False
        code_lines: list[str] = []
        
        for line in lines:
            if line.strip().startswith("```python") or line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block or (not any(line.strip().startswith("```") for _ in [None])):
                if not line.strip().startswith("```"):
                    code_lines.append(line)
        
        result = "\n".join(code_lines).strip()
        # If no code blocks found, return original
        return result if result else text.strip()

    def _render_script(
        self,
        prompt: str,
        images: Iterable[ImageInput],
        iteration_tag: str,
    ) -> str:
        image_list = list(images)
        prompt_lines = [line.strip() for line in prompt.splitlines() if line.strip()]
        title = prompt_lines[0] if prompt_lines else "Auto Generated Slide"
        bullet_lines = prompt_lines[1:] if len(prompt_lines) > 1 else []

        lines: list[str] = [
            f"# Auto generated script ({iteration_tag})",
            "import argparse",
            "import json",
            "from pathlib import Path",
            "from typing import Dict, Optional",
            "",
            "from pptx import Presentation",
            "from pptx.util import Inches, Pt",
            "",
            "",
            "def build_text_frame(slide, title_text, bullet_points):",
            "    left = Inches(0.6)",
            "    top = Inches(0.6)",
            "    width = Inches(12.1)",
            "    height = Inches(3.8)",
            "    textbox = slide.shapes.add_textbox(left, top, width, height)",
            "    text_frame = textbox.text_frame",
            "    text_frame.text = title_text",
            "    text_frame.paragraphs[0].font.size = Pt(40)",
            "    text_frame.paragraphs[0].font.bold = True",
            "    for bullet in bullet_points:",
            "        paragraph = text_frame.add_paragraph()",
            "        paragraph.text = bullet",
            "        paragraph.level = 1",
            "        paragraph.font.size = Pt(20)",
            "",
            "",
            "def place_images(slide, image_map):",
            "    image_specs = []",
        ]

        for img in image_list:
            lines.append(
                f"    image_specs.append((\"{img.name}\", image_map.get(\"{img.name}\"), {img.description!r}))"
            )

        lines.extend(
            [
                "    if not image_specs:",
                "        return",
                "    base_left = Inches(0.5)",
                "    base_top = Inches(4.5)",
                "    spacing = Inches(0.3)",
                "    image_width = Inches(2.8)",
                "    image_height = Inches(2.2)",
                "    max_per_row = max(1, min(3, len(image_specs)))",
                "    for index, (name, path, description) in enumerate(image_specs):",
                "        if not path:",
                "            continue",
                "        try:",
                "            column = index % max_per_row",
                "            row = index // max_per_row",
                "            left = base_left + (image_width + spacing) * column",
                "            top = base_top + (image_height + spacing) * row",
                "            slide.shapes.add_picture(path, left, top, width=image_width, height=image_height)",
                "            if description:",
                "                caption_top = min(top + image_height + Inches(0.1), Inches(7.0))",
                "                caption_box = slide.shapes.add_textbox(left, caption_top, image_width, Inches(0.6))",
                "                caption_frame = caption_box.text_frame",
                "                caption_frame.text = description",
                "                caption_frame.paragraphs[0].font.size = Pt(12)",
                "                caption_frame.paragraphs[0].font.italic = True",
                "        except Exception as error:  # pylint: disable=broad-except",
                "            print(f\"Failed to place image {name}: {error}\", flush=True)",
                "",
                "",
                "def main(output_path: Path, image_map: Optional[Dict[str, str]] = None):",
                "    image_map = image_map or {}",
                "    presentation = Presentation()",
                "    presentation.slide_width = Inches(13.33)",
                "    presentation.slide_height = Inches(7.5)",
                "    slide = presentation.slides.add_slide(presentation.slide_layouts[6])",
                "    bullet_points = []",
            ]
        )

        for bullet_line in bullet_lines or ["Generated overview based on the prompt."]:
            lines.append(f"    bullet_points.append({bullet_line!r})")

        lines.extend(
            [
                f"    build_text_frame(slide, {title!r}, bullet_points)",
                "    place_images(slide, image_map)",
                "    presentation.save(output_path)",
                "",
                "",
                "def parse_args():",
                '    parser = argparse.ArgumentParser(description="Generated slide authoring script")',
                '    parser.add_argument("--output", required=True, type=Path)',
                '    parser.add_argument("--images", required=False, type=Path)',
                "    return parser.parse_args()",
                "",
                "",
                "def load_image_map(images_path: Optional[Path]) -> Dict[str, str]:",
                "    if not images_path or not images_path.exists():",
                "        return {}",
                "    with images_path.open(\"r\", encoding=\"utf-8\") as handle:",
                "        return json.load(handle)",
                "",
                "",
                "if __name__ == \"__main__\":",
                "    args = parse_args()",
                "    image_map = load_image_map(args.images)",
                "    main(args.output, image_map)",
            ]
        )

        return "\n".join(lines)

    @staticmethod
    def _mock_request_id(seed: str) -> str:
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return f"mock-{digest[:12]}"

    def _render_template(self, name: str, **context: object) -> str:
        return self._prompt_store.render(name, **context)

    @staticmethod
    def _format_images(images: list[ImageInput]) -> str:
        if not images:
            return "(no images provided)"
        lines = ["- {name}: {description} ({path})".format(name=image.name, description=image.description, path=image.path)
                 for image in images]
        return "\n".join(lines)

    @staticmethod
    def _format_score(score: Optional[ScoreBreakdown]) -> str:
        if not score:
            return "No prior score available."
        return (
            f"Completeness={score.completeness}, "
            f"Content Accuracy={score.content_accuracy}, "
            f"Layout Match={score.layout_match}, "
            f"Visual Quality={score.visual_quality}, "
            f"Aggregate={score.aggregate}"
        )
