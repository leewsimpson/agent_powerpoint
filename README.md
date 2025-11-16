## Python SlideGen

Python SlideGen orchestrates an LLM driven workflow that converts prompt + images into a PPTX slide, complete with execution, screenshot capture, scoring, and iterative improvement loops. Prompt templates that steer the LLM live under `slidegen/prompt_templates/` and are loaded at runtime so they can be reviewed or customised without touching the codebase.

### Quick Start

**Prerequisites:**

Screenshot generation requires LibreOffice and PyMuPDF. See [HEADLESS_SETUP.md](HEADLESS_SETUP.md) for installation instructions for your platform.

**Setup:**

1. Create and populate a `.env` file (see `requirements.md`):
	```env
	OPENAI_USE_MOCK=true
	DEFAULT_OUTPUT_DIR=./runs
	```
	Add real OpenAI credentials (`OPENAI_API_KEY`, models, etc.) when ready to integrate with the API.

2. Install dependencies (using [uv](https://github.com/astral-sh/uv) as recommended):
	```sh
	uv sync
	```

3. Run the CLI (easy command after `uv sync`):
	```sh
	# Simple slide with text
	uv run slidegen --prompt "Quarterly Results\nRevenue up 25%\nExpanding to new markets"
	
	# With images
	uv run slidegen --prompt "Product Launch" --image logo|c:/images/logo.png|Company logo top-right --image chart|c:/images/chart.png|Sales chart center
	
	# From a file
	uv run slidegen --prompt-file presentation.txt
	
	# Use mock mode explicitly
	uv run slidegen --prompt "Team Overview" --mock-openai
	```

**What happens:**
- The CLI generates a PowerPoint slide based on your prompt
- The best slide is automatically saved to your workspace (e.g., `slide_20241116_123456.pptx`)
- All artifacts live under `runs/<run_id>/` for inspection
- A JSON summary shows the run ID, score, and file locations

### Development

- Execute the unit test suite:
  ```sh
  uv run pytest
  ```
- Run the orchestrator locally:
  ```sh
  uv run slidegen --prompt "Title\nBullet one" --mock-openai
  ```

### CLI Options

```
--prompt "text"              Inline prompt text (use \n for line breaks)
--prompt-file path.txt       Load prompt from a text file
--image name|path|desc       Add images (repeatable). Format: name|/path/to/image.png|description
--reference-image path.png   Optional reference layout image
--output-dir /custom/path    Override default output directory
--mock-openai                Force mock mode (generates deterministic slides)
--real-openai                Force real OpenAI API usage
--log-level DEBUG            Set logging level (DEBUG, INFO, WARNING, ERROR)
--run-id custom_id           Custom run identifier
```

**Examples:**

```sh
# Marketing slide with logo
uv run slidegen --prompt "New Campaign\n50% off all items\nLimited time only" --image logo|c:/assets/brand.png|Top left corner

# Technical presentation from file
uv run slidegen --prompt-file architecture.txt --image diagram|./diagrams/system.png|Center aligned architecture diagram

# Quick test in mock mode
uv run slidegen --prompt "Test Slide" --mock-openai --log-level DEBUG

# Production mode with real AI
uv run slidegen --prompt "Executive Summary\nQ4 2024 Results" --real-openai
```

### Architecture Highlights

- `slidegen.config`: loads `.env` + environment overrides into typed settings.
- `slidegen.prompt_store`: loads text prompt templates from disk and formats them for API calls.
- `slidegen.openai_client`: mock-friendly LLM façade that generates `python-pptx` scripts, implements fix/improve cycles, and provides lightweight scoring. Templates are read from disk before each request so a future OpenAI integration can use the same payloads.
- `slidegen.state`: state machine that drives generation, execution, fix loop, screenshot capture, scoring, and improvement iterations.
- `slidegen.execution`: runs generated scripts in a subprocess, enforces contracts, and validates PPTX output.
- `slidegen.screenshot`: captures screenshots using headless LibreOffice + PyMuPDF (server-friendly), or placeholder generation in mock mode.
- `slidegen.scoring`: aggregates model scores with configurable weights.

Refer to `AGENT.md` for applied guidelines during development.

### How The Workflow Runs

1. **Prompt intake** – The CLI validates the user prompt, optional image descriptors, and an optional reference layout image.
2. **Prompt templating** – `OpenAIClient` formats disk-based templates with the current run context (prompt text, images, iteration feedback).
3. **Script generation** – In mock mode a deterministic generator returns a `python-pptx` script; in production the formatted template will be sent to the OpenAI API.
4. **Script execution** – The `ExecutionEngine` runs the generated script via `uv run python …` when available, validates slide output, and persists logs.
5. **Screenshot capture** – `ScreenshotService` converts PPTX to image using headless LibreOffice + PyMuPDF and stores it with the run artifacts.
6. **Scoring** – `ScoringService` asks the LLM (via templates) to rate the slide, combines dimension scores using configured weights, and updates run metadata.
7. **Fix / improve loops** – Failures trigger the fix template; successful but sub-par slides re-enter the improvement loop until thresholds or iteration limits are met.
8. **Artifacts & metadata** – Every run produces scripts, PPTX files, screenshots, logs, and a metadata.json describing iteration lineage and scores.

The end-to-end process is captured in `runs/<run_id>/` so you can inspect every intermediate artifact.
