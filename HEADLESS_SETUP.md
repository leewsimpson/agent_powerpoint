# Headless Screenshot Setup

The system now supports **server-side, headless PPTX screenshot generation** that doesn't require a GUI or desktop environment.

## How It Works

**Headless Mode**: Uses LibreOffice in headless mode to convert PPTX → PDF → PNG
- No GUI required
- Works on servers and CI/CD environments
- Requires LibreOffice and PyMuPDF

**Mock Mode**: Creates placeholder images when LibreOffice is unavailable or in development

## Installation

### Windows

1. **Install LibreOffice**:
   ```powershell
   winget install TheDocumentFoundation.LibreOffice
   ```
   Or download from https://www.libreoffice.org/download/download/

2. **Install Python dependencies** (includes PyMuPDF for PDF rasterization):
   ```bash
   uv sync
   ```

### Linux (Ubuntu/Debian)

```bash
# Install LibreOffice
sudo apt-get update
sudo apt-get install -y libreoffice

# Install Python dependencies (includes PyMuPDF)
uv sync
```

### macOS

```bash
# Install LibreOffice
brew install --cask libreoffice

# Install Python dependencies (includes PyMuPDF)
uv sync
```

## Verification

The system will use headless rendering if LibreOffice is installed. Check the logs:

```
INFO - Converting PPTX to screenshot using LibreOffice and PyMuPDF
```

Or if unavailable (mock mode):

```
INFO - Creating placeholder screenshot (mock mode)
```

## Configuration

No additional configuration is needed. The system uses headless mode when LibreOffice is available, or mock mode otherwise.

## Benefits

- **Server-friendly**: No X11, display, or GUI required
- **CI/CD compatible**: Works in Docker containers and GitHub Actions
- **Simple**: Single method for screenshot generation
- **Quality**: Renders at 150 DPI for good quality without huge file sizes

## Troubleshooting

**Issue**: `FileNotFoundError: LibreOffice (soffice) executable not found`
- **Solution**: Install LibreOffice (see installation instructions above). Ensure it's in your system PATH.

**Issue**: `ImportError: No module named 'pymupdf'`
- **Solution**: Reinstall dependencies:
  ```bash
  uv sync
  ```

**Issue**: Screenshots are still placeholders
- **Solution**: Check logs for specific errors. Ensure LibreOffice is installed and in PATH. Verify PyMuPDF is installed with `uv pip list | grep pymupdf`.
