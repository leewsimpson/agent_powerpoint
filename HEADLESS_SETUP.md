# Headless Screenshot Setup

The system now supports **server-side, headless PPTX screenshot generation** that doesn't require a GUI or desktop environment.

## How It Works

1. **Headless Mode (Preferred)**: Uses LibreOffice in headless mode to convert PPTX → PDF → PNG
   - No GUI required
   - Works on servers and CI/CD environments
   - Requires LibreOffice and poppler-utils

2. **GUI Mode (Fallback)**: Uses the original viewer + mss screenshot capture
   - Requires a desktop environment
   - Falls back automatically if headless mode is unavailable

3. **Mock Mode**: Creates placeholder images
   - Used when both methods fail or in development

## Installation

### Windows

1. **Install LibreOffice**:
   ```powershell
   winget install TheDocumentFoundation.LibreOffice
   ```
   Or download from https://www.libreoffice.org/download/download/

2. **Install poppler** (for PDF to image conversion):
   ```powershell
   # Using Chocolatey
   choco install poppler
   
   # Or using conda
   conda install -c conda-forge poppler
   ```

3. **Install Python dependencies**:
   ```bash
   uv sync
   ```

### Linux (Ubuntu/Debian)

```bash
# Install LibreOffice
sudo apt-get update
sudo apt-get install -y libreoffice

# Install poppler-utils for pdf2image
sudo apt-get install -y poppler-utils

# Install Python dependencies
uv sync
```

### macOS

```bash
# Install LibreOffice
brew install --cask libreoffice

# Install poppler
brew install poppler

# Install Python dependencies
uv sync
```

## Verification

The system automatically detects if headless rendering is available. Check the logs:

```
INFO - Headless rendering available using: soffice
```

Or if unavailable:

```
INFO - Headless rendering not available (LibreOffice not found)
INFO - Creating placeholder screenshot (all methods failed)
```

## Configuration

No additional configuration is needed. The system will:
1. Try headless mode first
2. Fall back to GUI mode if headless fails
3. Use mock/placeholder if both fail

## Benefits

- **Server-friendly**: No X11, display, or GUI required
- **CI/CD compatible**: Works in Docker containers and GitHub Actions
- **Reliable**: LibreOffice headless is more stable than GUI automation
- **Quality**: Renders at 150 DPI for good quality without huge file sizes

## Troubleshooting

**Issue**: `FileNotFoundError: LibreOffice (soffice) executable not found`
- **Solution**: Install LibreOffice (see installation instructions above)

**Issue**: `ImportError: cannot import name 'convert_from_path'`
- **Solution**: Install pdf2image and poppler:
  ```bash
  uv pip install pdf2image
  # Then install poppler using your OS package manager
  ```

**Issue**: Screenshots are still placeholders
- **Solution**: Check logs for specific errors. Ensure both LibreOffice and poppler are installed and in PATH.
