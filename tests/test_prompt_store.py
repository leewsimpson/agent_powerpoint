from __future__ import annotations

import pytest
from pathlib import Path

from slidegen.prompt_store import PromptStore


def test_prompt_store_initialization():
    """Test PromptStore initializes with correct base directory."""
    store = PromptStore()
    assert store._base_dir.exists()
    assert store._base_dir.name == "prompt_templates"


def test_prompt_store_custom_base_dir(tmp_path):
    """Test PromptStore can use custom base directory."""
    custom_dir = tmp_path / "custom_templates"
    custom_dir.mkdir()
    (custom_dir / "test.txt").write_text("Hello {name}")
    
    store = PromptStore(base_dir=custom_dir)
    assert store._base_dir == custom_dir
    assert store.get("test") == "Hello {name}"


def test_prompt_store_missing_directory():
    """Test PromptStore raises error for missing directory."""
    with pytest.raises(FileNotFoundError, match="Prompt directory not found"):
        PromptStore(base_dir=Path("/nonexistent/path"))


def test_get_template():
    """Test getting a template loads content from disk."""
    store = PromptStore()
    content = store.get("initial_script")
    assert "You are an expert Python developer" in content
    assert "{prompt}" in content
    assert "{image_table}" in content


def test_get_template_with_txt_extension():
    """Test getting template works with .txt extension."""
    store = PromptStore()
    content1 = store.get("initial_script")
    content2 = store.get("initial_script.txt")
    assert content1 == content2


def test_get_template_missing():
    """Test getting missing template raises error."""
    store = PromptStore()
    with pytest.raises(FileNotFoundError, match="Prompt template missing"):
        store.get("nonexistent_template")


def test_template_caching():
    """Test templates are cached after first load."""
    store = PromptStore()
    content1 = store.get("initial_script")
    # Store in cache
    assert "initial_script" in store._cache
    # Second call should use cache
    content2 = store.get("initial_script")
    assert content1 == content2
    assert content1 is content2  # Same object reference


def test_render_simple_template(tmp_path):
    """Test rendering template with simple substitution."""
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "greeting.txt").write_text("Hello {username}, welcome to {place}!")
    
    store = PromptStore(base_dir=template_dir)
    result = store.render("greeting", username="Alice", place="Wonderland")
    assert result == "Hello Alice, welcome to Wonderland!"


def test_render_with_shared_templates():
    """Test rendering automatically injects shared templates."""
    store = PromptStore()
    result = store.render(
        "initial_script",
        prompt="Create a test slide",
        image_table="- img1: Test image (test.png)"
    )
    
    # Verify shared content is included
    assert "Implement a main(output_path, image_map=None)" in result
    assert "Import argparse, json, pathlib.Path" in result
    assert "MSO_AUTO_SHAPE_TYPE" in result
    assert "Create a test slide" in result


def test_shared_template_injection_for_initial_script():
    """Test shared templates are injected for initial_script template."""
    store = PromptStore()
    result = store.render("initial_script", prompt="Test", image_table="None")
    
    # Check all three shared templates are present
    assert "CRITICAL: The script MUST parse command-line arguments" in result
    assert "Example structure (you must follow this pattern)" in result
    assert "python-pptx documentation reminder" in result


def test_shared_template_injection_for_fix_script():
    """Test shared templates are injected for fix_script template."""
    store = PromptStore()
    result = store.render(
        "fix_script",
        prompt="Test",
        image_table="None",
        failing_script="# broken",
        error_log="Error"
    )
    
    assert "CRITICAL: The script MUST parse command-line arguments" in result
    assert "Example structure (you must follow this pattern)" in result
    assert "python-pptx documentation reminder" in result
    assert "# broken" in result


def test_shared_template_injection_for_improve_script():
    """Test shared templates are injected for improve_script template."""
    store = PromptStore()
    result = store.render(
        "improve_script",
        prompt="Test",
        image_table="None",
        previous_script="# old",
        previous_screenshot="screenshot.png",
        score_feedback="Score: 80",
        iteration_index=2
    )
    
    assert "CRITICAL: The script MUST parse command-line arguments" in result
    assert "Example structure (you must follow this pattern)" in result
    assert "# old" in result
    assert "Iteration Index: 2" in result


def test_render_without_shared_templates(tmp_path):
    """Test rendering template without shared references works normally."""
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "simple.txt").write_text("Just {value}")
    
    store = PromptStore(base_dir=template_dir)
    result = store.render("simple", value="text")
    assert result == "Just text"


def test_explicit_shared_template_override():
    """Test explicitly provided shared templates override auto-injection."""
    store = PromptStore()
    custom_requirements = "Custom requirements content"
    result = store.render(
        "initial_script",
        prompt="Test",
        image_table="None",
        shared_requirements=custom_requirements
    )
    
    assert custom_requirements in result
    assert "CRITICAL: The script MUST parse" not in result  # Original not used


def test_normalize_name():
    """Test name normalization removes .txt extension."""
    assert PromptStore._normalize_name("template.txt") == "template"
    assert PromptStore._normalize_name("template") == "template"
    assert PromptStore._normalize_name("  template.txt  ") == "template"
    assert PromptStore._normalize_name("  template  ") == "template"


def test_get_all_shared_templates():
    """Test all shared templates can be loaded."""
    store = PromptStore()
    
    requirements = store.get("shared_requirements")
    assert "Implement a main(output_path, image_map=None)" in requirements
    
    structure = store.get("shared_structure")
    assert "Import argparse, json, pathlib.Path" in structure
    
    api = store.get("shared_pptx_api")
    assert "MSO_AUTO_SHAPE_TYPE" in api
    assert "Presentation objects" in api


def test_score_slide_template_no_shared_injection():
    """Test score_slide template doesn't trigger shared template injection."""
    store = PromptStore()
    result = store.render(
        "score_slide",
        prompt="Test",
        image_table="None",
        screenshot_path="screenshot.png",
        reference_image="ref.png"
    )
    
    # Should not contain shared templates since score_slide doesn't reference them
    assert "CRITICAL: The script MUST parse" not in result
    assert "Return JSON with keys" in result


def test_missing_context_variable_raises_error(tmp_path):
    """Test missing context variable raises KeyError."""
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "test.txt").write_text("Hello {username}")
    
    store = PromptStore(base_dir=template_dir)
    with pytest.raises(KeyError):
        store.render("test")  # Missing 'username' parameter


def test_multiple_templates_same_store():
    """Test using same PromptStore instance for multiple templates."""
    store = PromptStore()
    
    result1 = store.render("initial_script", prompt="Test 1", image_table="None")
    result2 = store.render("fix_script", prompt="Test 2", image_table="None", 
                          failing_script="code", error_log="error")
    result3 = store.render("score_slide", prompt="Test 3", image_table="None",
                          screenshot_path="shot.png", reference_image="ref.png")
    
    assert "Test 1" in result1
    assert "Test 2" in result2
    assert "Test 3" in result3
    
    # Verify cache is populated
    assert len(store._cache) >= 6  # 3 main templates + 3 shared templates


def test_shared_templates_cached_once():
    """Test shared templates are loaded and cached only once."""
    store = PromptStore()
    
    # First render loads shared templates
    store.render("initial_script", prompt="Test 1", image_table="None")
    cache_size_1 = len(store._cache)
    
    # Second render should reuse cached shared templates
    store.render("fix_script", prompt="Test 2", image_table="None",
                failing_script="code", error_log="error")
    cache_size_2 = len(store._cache)
    
    # Cache should only grow by 1 (fix_script), not by 4 (fix_script + 3 shared)
    assert cache_size_2 == cache_size_1 + 1
