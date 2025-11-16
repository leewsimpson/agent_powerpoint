"""Integration tests for prompt template composition system."""
from __future__ import annotations

from pathlib import Path

from slidegen.config import OpenAIConfig
from slidegen.openai_client import OpenAIClient
from slidegen.prompt_store import PromptStore
from slidegen.types import ImageInput, ScoreBreakdown


def test_end_to_end_template_composition():
    """Test complete workflow using template composition."""
    config = OpenAIConfig(api_key=None, default_model="gpt-test", vision_model="gpt-test", mock_mode=True)
    client = OpenAIClient(config)
    
    images = [
        ImageInput(name="graph", path=Path("graph.png"), description="Performance graph"),
        ImageInput(name="logo", path=Path("logo.png"), description="Brand logo"),
    ]
    
    # Step 1: Generate initial script
    initial_result = client.generate_initial_script("Annual Review\nKey Highlights", images)
    
    # Validate initial script includes all shared content
    assert "Implement a main(output_path, image_map=None)" in initial_result.prompt_payload
    assert "Import argparse, json, pathlib.Path" in initial_result.prompt_payload
    assert "MSO_AUTO_SHAPE_TYPE" in initial_result.prompt_payload
    assert "Annual Review" in initial_result.prompt_payload
    assert "graph: Performance graph" in initial_result.prompt_payload
    
    # Validate generated script structure
    assert "def main(output_path" in initial_result.script
    assert "if __name__ == \"__main__\":" in initial_result.script
    assert initial_result.request_id.startswith("mock-")
    
    # Step 2: Fix script (simulating an error)
    fix_result = client.fix_script(
        "Annual Review\nKey Highlights",
        images,
        failing_script=initial_result.script,
        error_log="NameError: name 'Pt' is not defined"
    )
    
    # Validate fix script includes shared content and error context
    assert "Implement a main(output_path, image_map=None)" in fix_result.prompt_payload
    assert "NameError: name 'Pt' is not defined" in fix_result.prompt_payload
    assert "def main(output_path" in fix_result.script
    
    # Step 3: Improve script based on feedback
    score = ScoreBreakdown(
        completeness=75.0,
        content_accuracy=80.0,
        layout_match=70.0,
        visual_quality=72.0,
        aggregate=74.25
    )
    
    improve_result = client.improve_script(
        "Annual Review\nKey Highlights",
        images,
        previous_script=fix_result.script,
        score_feedback=score,
        iteration_index=2
    )
    
    # Validate improvement includes shared content and feedback
    assert "Implement a main(output_path, image_map=None)" in improve_result.prompt_payload
    assert "Iteration Index: 2" in improve_result.prompt_payload
    assert "Completeness=75.0" in improve_result.prompt_payload
    assert "def main(output_path" in improve_result.script


def test_score_slide_template_independent():
    """Test that score_slide template is independent of script templates."""
    store = PromptStore()
    score_template = store.get("score_slide")
    
    # Score template should not reference shared script templates
    assert "{shared_requirements}" not in score_template
    assert "{shared_structure}" not in score_template
    assert "{shared_pptx_api}" not in score_template
    
    # It should have its own content
    assert "{prompt}" in score_template
    assert "{screenshot_path}" in score_template


def test_template_composition_with_no_images():
    """Test template composition works correctly with empty image lists."""
    config = OpenAIConfig(api_key=None, default_model="gpt-test", vision_model="gpt-test", mock_mode=True)
    client = OpenAIClient(config)
    
    result = client.generate_initial_script("Simple slide with no images", [])
    
    assert "Implement a main(output_path, image_map=None)" in result.prompt_payload
    assert "(no images provided)" in result.prompt_payload
    assert "def main(output_path" in result.script


def test_template_composition_with_many_images():
    """Test template composition handles multiple images correctly."""
    config = OpenAIConfig(api_key=None, default_model="gpt-test", vision_model="gpt-test", mock_mode=True)
    client = OpenAIClient(config)
    
    images = [
        ImageInput(name=f"img{i}", path=Path(f"img{i}.png"), description=f"Image {i}")
        for i in range(5)
    ]
    
    result = client.generate_initial_script("Multi-image slide", images)
    
    # Verify all images are in the prompt
    for i in range(5):
        assert f"img{i}: Image {i}" in result.prompt_payload
    
    # Verify shared content is still present
    assert "Implement a main(output_path, image_map=None)" in result.prompt_payload


def test_prompt_payload_deterministic():
    """Test that prompt payloads are deterministic for same inputs."""
    config = OpenAIConfig(api_key=None, default_model="gpt-test", vision_model="gpt-test", mock_mode=True)
    client = OpenAIClient(config)
    image = ImageInput(name="test", path=Path("test.png"), description="Test image")
    
    # Generate same prompt twice
    result1 = client.generate_initial_script("Test slide", [image])
    result2 = client.generate_initial_script("Test slide", [image])
    
    # Prompt payloads should be identical
    assert result1.prompt_payload == result2.prompt_payload
    
    # Request IDs should also be identical in mock mode (deterministic hashing)
    assert result1.request_id == result2.request_id


def test_template_composition_preserves_context():
    """Test that template composition doesn't lose custom context."""
    config = OpenAIConfig(api_key=None, default_model="gpt-test", vision_model="gpt-test", mock_mode=True)
    client = OpenAIClient(config)
    image = ImageInput(name="test", path=Path("test.png"), description="Test image")
    
    custom_prompt = "Very specific slide requirements\nWith multiple lines\nAnd details"
    result = client.generate_initial_script(custom_prompt, [image])
    
    # Custom prompt should be preserved exactly
    assert "Very specific slide requirements" in result.prompt_payload
    assert "With multiple lines" in result.prompt_payload
    assert "And details" in result.prompt_payload
    
    # Shared content should also be present
    assert "Implement a main(output_path, image_map=None)" in result.prompt_payload


def test_iteration_tracking_in_improvements():
    """Test that iteration tracking works correctly in improvement prompts."""
    config = OpenAIConfig(api_key=None, default_model="gpt-test", vision_model="gpt-test", mock_mode=True)
    client = OpenAIClient(config)
    image = ImageInput(name="test", path=Path("test.png"), description="Test")
    
    # Test different iterations
    for iteration in [1, 2, 5, 10]:
        result = client.improve_script(
            "Test",
            [image],
            "# previous script",
            None,
            iteration
        )
        assert f"Iteration Index: {iteration}" in result.prompt_payload


def test_error_context_preserved_in_fix():
    """Test that error context is fully preserved in fix prompts."""
    config = OpenAIConfig(api_key=None, default_model="gpt-test", vision_model="gpt-test", mock_mode=True)
    client = OpenAIClient(config)
    image = ImageInput(name="test", path=Path("test.png"), description="Test")
    
    detailed_error = """Traceback (most recent call last):
  File "script.py", line 42, in main
    shape.text_frame.text = title
AttributeError: 'NoneType' object has no attribute 'text_frame'
"""
    
    result = client.fix_script("Test", [image], "# broken code", detailed_error)
    
    # Verify complete error is in prompt
    assert "Traceback (most recent call last):" in result.prompt_payload
    assert "AttributeError: 'NoneType' object has no attribute 'text_frame'" in result.prompt_payload
    assert "# broken code" in result.prompt_payload


def test_score_feedback_formatting():
    """Test that score feedback is correctly formatted in improvement prompts."""
    config = OpenAIConfig(api_key=None, default_model="gpt-test", vision_model="gpt-test", mock_mode=True)
    client = OpenAIClient(config)
    image = ImageInput(name="test", path=Path("test.png"), description="Test")
    
    score = ScoreBreakdown(
        completeness=85.5,
        content_accuracy=90.25,
        layout_match=78.75,
        visual_quality=82.0,
        aggregate=84.125
    )
    
    result = client.improve_script("Test", [image], "# code", score, 1)
    
    # Verify all score components are present with correct formatting
    assert "Completeness=85.5" in result.prompt_payload
    assert "Content Accuracy=90.25" in result.prompt_payload
    assert "Layout Match=78.75" in result.prompt_payload
    assert "Visual Quality=82.0" in result.prompt_payload
    assert "Aggregate=84.125" in result.prompt_payload
