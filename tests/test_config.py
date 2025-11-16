from __future__ import annotations

from pathlib import Path

from slidegen.config import load_settings


def test_load_settings_mock_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_USE_MOCK", "true")
    monkeypatch.setenv("DEFAULT_OUTPUT_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    settings = load_settings()
    assert settings.openai.mock_mode is True
    assert settings.io.default_output_dir == Path(tmp_path / "runs")
    assert settings.io.default_output_dir.exists()
    assert settings.score_weights.total == 1.0
    assert settings.screenshot.window_search_timeout_seconds == 10.0
    assert settings.screenshot.focus_delay_seconds == 0.6
