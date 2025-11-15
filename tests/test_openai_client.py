from __future__ import annotations

from pathlib import Path

from slidegen.config import OpenAIConfig
from slidegen.openai_client import OpenAIClient
from slidegen.prompt_store import PromptStore
from slidegen.types import ImageInput


def test_generated_script_uses_captions_and_optional_image_map() -> None:
    config = OpenAIConfig(api_key=None, default_model="gpt-test", vision_model="gpt-test", mock_mode=True)
    client = OpenAIClient(config)
    image = ImageInput(name="logo", path=Path("logo.png"), description="Company logo caption")

    result = client.generate_initial_script("Title\nPoint", [image])

    assert "def main(output_path: Path, image_map: Optional[Dict[str, str]] = None):" in result.script
    assert "image_map = image_map or {}" in result.script
    assert "caption_frame.text = description" in result.script
    assert "logo" in result.prompt_payload


class RecordingPromptStore(PromptStore):
    def __init__(self) -> None:
        super().__init__()
        self.render_calls: list[str] = []

    def render(self, name: str, **context: object) -> str:  # type: ignore[override]
        self.render_calls.append(name)
        return super().render(name, **context)


def test_prompts_loaded_from_disk() -> None:
    config = OpenAIConfig(api_key=None, default_model="gpt-test", vision_model="gpt-test", mock_mode=True)
    store = RecordingPromptStore()
    client = OpenAIClient(config, prompt_store=store)

    image = ImageInput(name="icon", path=Path("icon.png"), description="Important badge")
    client.generate_initial_script("Brief", [image])
    client.fix_script("Brief", [image], failing_script="print('fail')", error_log="Traceback")
    client.improve_script("Brief", [image], previous_script="print('ok')", score_feedback=None, iteration_index=1)

    assert "initial_script" in store.render_calls
    assert "fix_script" in store.render_calls
    assert "improve_script" in store.render_calls
