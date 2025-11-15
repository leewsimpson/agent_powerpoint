## Python SlideGen

Python SlideGen orchestrates an LLM driven workflow that converts prompt + images into a PPTX slide, complete with execution, screenshot capture, scoring, and iterative improvement loops. Prompt templates that steer the LLM live under `slidegen/prompt_templates/` and are loaded at runtime so they can be reviewed or customised without touching the codebase.

### Quick Start

Windows:
choco install libreoffice-fresh
choco install poppler

Mac:
brew ..

1. Create and populate a `.env` file (see `requirements.md`):
	```env
	OPENAI_USE_MOCK=true
	DEFAULT_OUTPUT_DIR=./runs
	```
	Add real OpenAI credentials (`OPENAI_API_KEY`, models, viewer commands, etc.) when you are ready to integrate with the API.
2. Install dependencies (using [uv](https://github.com/astral-sh/uv) as recommended):
	```sh
	uv sync
	```
3. Run the CLI:
	```sh
	uv run python -m slidegen.cli --prompt "Sample Slide\nKey point" --image logo|/absolute/path/logo.png|Place logo top-right
	```

The CLI prints a JSON summary containing the run id, best score, and output location. All artifacts (prompt, scripts, PPTX files, screenshots, logs, metadata) live under `runs/<run_id>/` by default.

### Development

- Execute the unit test suite:
  ```sh
  uv run pytest
  ```
- Run the orchestrator locally with the helper script:
  ```sh
  uv run python main.py --prompt "Title\nBullet one" --mock-openai
  ```

### Architecture Highlights

- `slidegen.config`: loads `.env` + environment overrides into typed settings.
- `slidegen.prompt_store`: loads text prompt templates from disk and formats them for API calls.
- `slidegen.openai_client`: mock-friendly LLM façade that generates `python-pptx` scripts, implements fix/improve cycles, and provides lightweight scoring. Templates are read from disk before each request so a future OpenAI integration can use the same payloads.
- `slidegen.state`: state machine that drives generation, execution, fix loop, screenshot capture, scoring, and improvement iterations.
- `slidegen.execution`: runs generated scripts in a subprocess, enforces contracts, and validates PPTX output.
- `slidegen.screenshot`: captures screenshots via `pyautogui` when available or emits placeholders via Pillow.
- `slidegen.scoring`: aggregates model scores with configurable weights.

Refer to `AGENT.md` for applied guidelines during development.

### How The Workflow Runs

1. **Prompt intake** – The CLI validates the user prompt, optional image descriptors, and an optional reference layout image.
2. **Prompt templating** – `OpenAIClient` formats disk-based templates with the current run context (prompt text, images, iteration feedback).
3. **Script generation** – In mock mode a deterministic generator returns a `python-pptx` script; in production the formatted template will be sent to the OpenAI API.
4. **Script execution** – The `ExecutionEngine` runs the generated script via `uv run python …` when available, validates slide output, and persists logs.
5. **Screenshot capture** – `ScreenshotService` opens the PPTX, captures a screenshot (or placeholder), and stores it with the run artifacts.
6. **Scoring** – `ScoringService` asks the LLM (via templates) to rate the slide, combines dimension scores using configured weights, and updates run metadata.
7. **Fix / improve loops** – Failures trigger the fix template; successful but sub-par slides re-enter the improvement loop until thresholds or iteration limits are met.
8. **Artifacts & metadata** – Every run produces scripts, PPTX files, screenshots, logs, and a metadata.json describing iteration lineage and scores.

The end-to-end process is captured in `runs/<run_id>/` so you can inspect every intermediate artifact.
