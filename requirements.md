# Python SlideGen: Requirements & Design

## 1. Purpose

Python SlideGen is a Python based workflow that takes a **natural language slide brief** plus **optional images** and produces a **PowerPoint (.pptx) slide**, iteratively improving the underlying generation script using the OpenAI API.

The system:

1. Accepts a high level prompt describing the desired slide (content, structure, style, branding).
2. Accepts zero or more **input images**, each with:
   * a unique name, and
   * a short description explaining what the image is and how it should be used.
3. Uses an LLM to generate a Python script that uses `python-pptx` to build the slide and embed the requested images.
4. Executes the generated script in a controlled environment to produce a PPTX.
5. Uses `pyautogui` to capture a screenshot of the slide for visual comparison.
6. If the script fails, an LLM based fix loop repairs the code up to a configurable retry limit.
7. If the slide is generated but not good enough, an LLM driven improvement loop refines the script using:

   * side by side image comparison
   * a **slide scoring mechanism** that combines several dimensions into a single score.

The control flow follows the original diagram, with explicit states for:

* Initial Generation
* Execute Python
* Script Error and Fix Loop
* Improvement Loop (Image Generated and Scored)

---

## 2. High Level Architecture

### 2.1 Components

#### 2.1.1 CLI Orchestrator

* Entry point for the workflow.
* Uses **uv** as the package and environment manager to run the program and manage dependencies.
* Accepts:

  * Slide prompt (required).
  * Zero or more input images with associated names and descriptions.
  * Optional reference layout image (ideal overall look and feel).
  * Configuration overrides such as retry counts and output directories.
* Triggers and coordinates all other components and stages.

#### 2.1.2 Configuration Layer

* All configuration values are stored primarily in a **`.env`** file, with support for overriding via environment variables and CLI.
* Example configuration values:

  * OpenAI:

    * `OPENAI_API_KEY`
    * `OPENAI_DEFAULT_MODEL`
    * `OPENAI_VISION_MODEL`
  * Behavior:

    * `MAX_SCRIPT_RETRIES`
    * `MAX_IMPROVEMENT_ITERATIONS`
    * `EXECUTION_TIMEOUT_SECONDS`
    * `TARGET_SCORE_THRESHOLD`
  * IO and environment:

    * `DEFAULT_OUTPUT_DIR`
    * `PPTX_VIEWER_COMMAND_WINDOWS`
    * `PPTX_VIEWER_COMMAND_MACOS`
* On startup the application:

  * Loads `.env`.
  * Validates required keys like `OPENAI_API_KEY`.
  * Exposes a typed configuration object to the rest of the system so code never reads environment variables directly.

#### 2.1.3 OpenAI Client Layer

* Abstraction over the OpenAI Python SDK.
* Responsibilities:

  * Handle authentication from `.env` / environment.
  * Provide high level functions:

    * Generate initial script from prompt and image list.
    * Fix script using error logs.
    * Improve script using screenshots, reference layout, prompt, and scoring guidance.
    * Compute slide scores (single scalar) from multi component evaluation.
  * Load system/user prompts from external template files (no inline prompts in code) so prompt content can be audited and updated without code changes.
  * Centralize:

    * Model names and parameters.
    * Common system prompts and safety settings.
    * Retry policy for transient API errors.

#### 2.1.4 Script Manager

* Persists and versions all generated Python scripts.
* Stores per version metadata:

  * Version id.
  * Origin (initial, fix, improvement).
  * Parent version id for lineage.
  * Associated OpenAI request id.
  * Execution status (pending, success, failure).
* File structure per run (example):

  * `runs/<run_id>/scripts/script_v1_initial.py`
  * `runs/<run_id>/scripts/script_v2_fixed.py`
  * `runs/<run_id>/scripts/script_v3_improved_1.py`

#### 2.1.5 Execution Engine

* Executes generated scripts in an isolated subprocess within the **uv** managed environment.
* Responsibilities:

  * Invoke scripts with a standard interface (for example `--output` for PPTX path and a configuration file or env var for image mapping).
  * Enforce execution timeout using configuration.
  * Capture exit code, stdout, and stderr to log files.
* Safety constraints:

  * Limit script access to per run working directory.
  * Prohibit network access.
  * Avoid direct shell command execution inside generated scripts beyond what is strictly required.

#### 2.1.6 Slide Authoring Contract

* Generated scripts must use **`python-pptx`** as the single library for PPTX creation.
* Contract:

  * Define a `main(output_path)` function that creates a single **16:9** slide.
  * Use `python-pptx` APIs to:

    * Add title, body text, shapes, and charts.
    * Insert images based on a mapping from `image_name` to file path.
  * When executed as a script:

    * Parse command line arguments or a config file for `output_path` and image paths.
    * Call `main(output_path)`.

#### 2.1.7 Screenshot and Image Capture Layer

* Uses **`pyautogui`** to take a screenshot of the generated slide.
* Responsibilities:

  * Coordinate with a platform specific viewer to open the PPTX.
  * Wait for the slide to be visible.
  * Focus the viewer window.
  * Capture either the full screen or a configured region containing the slide.
  * Save screenshot as `slide_vX.png` under `runs/<run_id>/outputs/`.
  * Optionally close or minimize the viewer window afterwards.

#### 2.1.8 Viewer Abstraction

* Provides a small OS aware abstraction around PPTX viewing.
* Uses `.env` values, for example:

  * `PPTX_VIEWER_COMMAND_WINDOWS` on Windows.
  * `PPTX_VIEWER_COMMAND_MACOS` on macOS.
* Responsibilities:

  * Launch the viewer with parameters that open the PPTX on the first slide, ideally in slideshow or full screen mode.
  * Provide hints to the screenshot layer (window title, expected delays).

#### 2.1.9 Artifact Manager

* Manages all file based artifacts for each run:

  * `input/`:

    * `prompt.txt`
    * reference layout image copy, if any
    * user supplied images, renamed or symlinked to stable paths
  * `scripts/`:

    * all script versions with clear naming
  * `outputs/`:

    * PPTX files
    * screenshots corresponding to each PPTX
  * `logs/`:

    * execution logs
    * API interaction logs (sanitized)
    * configuration snapshot
    * run level `metadata.json` (see below)

#### 2.1.10 Evaluation, Scoring, and Control Logic

* Encapsulates the state machine:

  * Initial Generation
  * Execute Script
  * Fix Script Loop
  * Screenshot Capture
  * Improvement Loop (repeated)
* Uses a **composite slide scoring mechanism** to drive decisions:

  * Computes a **single scalar score**, but derived from weighted components such as:

    * Completeness (are all requested elements and images present)
    * Content accuracy (does text content reflect the prompt)
    * Layout match (how well layout aligns with the prompt and optional reference image)
    * Visual quality (readability, spacing, alignment, legibility)
  * Each component is scored separately by the OpenAI model, then combined using configurable weights into a final score between 0 and 100.
* Control decisions include:

  * Whether to attempt improvement iterations based on score versus `TARGET_SCORE_THRESHOLD`.
  * When to stop improvements (threshold reached or `MAX_IMPROVEMENT_ITERATIONS`).
  * Which slide and script version to select as the final result (highest score).

---

## 3. Detailed Workflow

### 3.1 Inputs

#### 3.1.1 Prompt (required)

Free form natural language description of the desired slide. Can include:

* Narrative of what the slide should communicate.
* Important bullet points, charts, and callouts.
* Brand or styling guidance (colors, fonts, tone).
* Structural hints (columns, visual hierarchy, relationships).

#### 3.1.2 Image List (zero or more items)

Each input image is provided with:

* `image_name` (unique identifier used in prompts and code).
* `image_path` (location where the orchestrator can access or copy the file).
* `image_description` describing:

  * What the image represents (for example company logo, map, photo, icon).
  * How it should be used on the slide (hero background, small badge in corner, next to a specific bullet, etc).

The orchestrator passes this structured list to the OpenAI client and ensures a stable mapping from `image_name` to actual file path for the generated script.

#### 3.1.3 Optional Reference Layout Image

* Single image that represents the desired overall layout and style.
* Used for:

  * Slide scoring.
  * Improvement loop prompts (visual comparison with generated screenshots).

#### 3.1.4 Configuration

* Derived from `.env` and from CLI overrides.
* Includes:

  * Retry and iteration limits.
  * Execution timeout.
  * Score threshold.
  * Paths and viewer commands.

---

### 3.2 Initial Generation

1. CLI collects:

   * Prompt.
   * Image list with names and descriptions.
   * Optional reference layout image.
   * Configuration overrides.
2. Orchestrator prepares a structured OpenAI request:

   * System message describing the role of the model (expert Python developer and slide designer).
   * User content including:

     * The prompt.
     * Tabular or bullet list of images with name, description, and intended usage.
     * Requirements to:

       * Use `python-pptx`.
       * Create a 16:9 slide.
       * Define a `main(output_path)` entry point.
       * Avoid external network calls.
3. OpenAI client sends the request and receives a complete Python script as text.
4. Script Manager saves this as `script_v1_initial.py` with metadata.

---

### 3.3 Script Execution

1. Execution Engine runs `script_v1_initial.py` in a subprocess within the **uv** managed environment.
2. It passes:

   * `--output` path for the PPTX.
   * A configuration structure or environment variable that maps `image_name` to local image file paths.
3. On completion:

   * It checks the exit code.
   * Validates that the PPTX exists and can be opened using `python-pptx` (for example verifying that at least one slide is present).
4. If successful, the workflow moves to screenshot capture.
5. If not, the workflow enters the fix script loop.

---

### 3.4 Fix Script Loop

1. `MAX_SCRIPT_RETRIES` is read from configuration.
2. For each failed attempt:

   * Orchestrator gathers:

     * Current script text.
     * Execution logs including full traceback.
   * Calls `fix_script_from_error` via the OpenAI client, giving both script and log.
   * Receives a repaired script, which:

     * Preserves the `python-pptx` approach and `main(output_path)` contract.
     * Addresses the specific error(s) encountered.
   * Script Manager saves this as a new version and marks the parent accordingly.
   * Execution Engine reruns the new version and validates again.
3. Termination:

   * On first successful run, proceed to screenshot capture.
   * If all retries fail, the run is marked as `FAILED_SCRIPT_ERROR`, with logs and scripts recorded for analysis.

---

### 3.5 Screenshot Capture with pyautogui

After a successful PPTX generation:

1. The viewer abstraction:

   * Determines the correct viewer command from configuration, based on whether the program is running on Windows or macOS.
   * Launches the PPTX viewer to display the generated slide (ideally first slide in fullscreen or slideshow mode).
2. The screenshot module:

   * Waits for a configurable delay for the viewer to load.
   * Uses `pyautogui` to:

     * Focus the viewer window (window title heuristics or keyboard shortcuts).
     * Capture:

       * Full primary screen, or
       * A configured region where the slide is expected to appear.
   * Saves the screenshot as `slide_vN.png` in the run’s `outputs` directory.
3. The viewer may optionally be closed or minimized after capture.
4. If screenshot capture fails:

   * The system may retry a small configurable number of times.
   * On repeated failure, the run is marked as failed with clear diagnostic logs.

---

### 3.6 Slide Scoring

Slide scoring is used both to drive the improvement loop and to select the best output.

1. Inputs to scoring:

   * Original prompt.
   * Structured image list (names, descriptions, intended use).
   * Screenshot of the generated slide.
   * Optional reference layout image.
2. Scoring dimensions:

   * **Completeness**

     * Have all requested major elements (titles, bullets, diagrams, images) been represented?
   * **Content Accuracy**

     * Does on slide text correctly reflect the prompt’s points and emphasis?
   * **Layout Match**

     * How closely does the overall layout match the requested layout and, when provided, the reference image (positioning, hierarchy, relative sizing)?
   * **Visual Quality**

     * Readability, spacing, alignment, and overall aesthetic coherence.
3. Scoring mechanism:

   * OpenAI model receives:

     * Textual description of scoring dimensions and weightings.
     * Prompt and metadata.
     * Screenshot (and reference layout if available).
   * It returns:

     * Individual scores for each dimension, for example 0–100 per dimension.
     * A single **aggregated score** between 0 and 100 computed using configurable weights, for example:

       * 30 percent Completeness
       * 30 percent Content Accuracy
       * 25 percent Layout Match
       * 15 percent Visual Quality
   * The aggregated score is used to:

     * Compare versions.
     * Decide whether to trigger further improvement iterations.

---

### 3.7 Improvement Loop

1. Initial scoring is performed on the first generated slide.
2. If the aggregated score is below `TARGET_SCORE_THRESHOLD`, or if a fixed number of improvement iterations has been requested, the system enters the improvement loop.
3. For each improvement iteration (up to `MAX_IMPROVEMENT_ITERATIONS`):

   * The OpenAI client calls the improvement function with:

     * Original prompt.
     * Current script text.
     * Current screenshot.
     * Optional reference layout image.
     * Structured image list (names and descriptions).
     * Previous dimension scores and overall score (to focus improvements).
   * The model:

     * Analyses where the slide is weak (for example layout match or completeness).
     * Produces a revised Python script that still uses `python-pptx` and the `main(output_path)` contract.
   * Script Manager stores the revised script version.
   * Execution Engine runs the script and validates the PPTX.
   * Screenshot layer captures a new screenshot.
   * Scoring module recomputes dimension scores and overall score.
   * The orchestrator updates:

     * The best score seen so far.
     * The script and artifact pointers for that best score.
   * If the new score exceeds the threshold, the loop may terminate early.
4. After the loop finishes:

   * The highest scoring slide (not necessarily the last) is selected as the final result.
   * Run metadata records:

     * Each iteration’s scores.
     * The chosen final version.

---

## 4. Configuration and Environment Management

### 4.1 uv

* `uv` is the standard mechanism for:

  * Creating project environments.
  * Installing dependencies.
  * Running the CLI.
* Documentation should show:

  * Initial setup using `uv`.
  * How to run SlideGen commands with `uv run`.

### 4.2 .env Configuration

* `.env` is the primary configuration file.
* All sensitive values (OpenAI keys) must remain only in `.env` or external environment variables.
* The configuration layer:

  * Loads `.env` once at startup.
  * Validates required keys.
  * Provides typed accessors for all parts of the system.

---

## 5. Functional Requirements Summary

1. Accept a detailed textual prompt.
2. Accept zero or many images, each with a name and description, and ensure they are accessible to generated scripts.
3. Optionally accept a reference layout image.
4. Generate a Python script using OpenAI that:

   * Uses `python-pptx`.
   * Creates a single 16:9 slide.
   * Appropriately incorporates supplied images.
5. Execute the script using the `uv` managed environment, and validate the resulting PPTX.
6. If execution fails, repair the script using OpenAI and retry up to `MAX_SCRIPT_RETRIES`.
7. After a successful PPTX generation, open it in a viewer and capture a screenshot using `pyautogui`.
8. Score the slide using a composite scoring model that returns a single aggregated score based on multiple dimensions.
9. Enter an improvement loop when the score is below threshold or when configured to do so, repeating:

   * Script improvement via OpenAI.
   * Re execution and PPTX generation.
   * Screenshot capture.
   * Re scoring.
10. Stop when the target score is reached or `MAX_IMPROVEMENT_ITERATIONS` is exhausted.
11. Select the highest scoring slide as the final output and persist:

    * Final script.
    * Final PPTX.
    * Final screenshot.
    * Score breakdown.
12. Persist all intermediate artifacts, logs, and metadata under a unique run id.

---

## 6. Non Functional Requirements

1. **Security and Safety**

   * Generated scripts run with limited privileges and no network access.
   * File operations are restricted to per run directories.
   * `.env` is never checked into version control.

2. **Portability**

   * Must work on **both Windows and macOS**:

     * Use OS specific viewer commands from `.env`.
     * `pyautogui` configuration (hotkeys, window titles, screen regions) must be configurable per OS.
   * When OS detection is ambiguous, a clear error or configuration hint should be provided.

3. **Reliability**

   * Viewer processes are cleaned up when runs complete.
   * Transient API errors use limited retries.
   * All failures provide clear messages and point to logs.

4. **Observability**

   * Structured logs with run id, timestamps, and stage markers.
   * Per run metadata file summarising:

     * Configuration used.
     * Script version lineage.
     * Scores per iteration.
     * Final chosen version and score.

5. **Extensibility**

   * Architecture should allow further evolution (for example additional scoring dimensions, multi slide support) without major redesign, although these are out of scope for the current requirements.
