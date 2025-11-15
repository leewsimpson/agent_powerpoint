from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .config import ScreenshotConfig
from .viewer import ViewerLauncher

try:
    import mss
except ImportError:
    mss = None  # type: ignore[assignment]

try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class ScreenshotService:
    def __init__(self, config: ScreenshotConfig, viewer: ViewerLauncher, mock_mode: bool) -> None:
        self._config = config
        self._viewer = viewer
        self._mock_mode = mock_mode
        self._headless_mode = self._detect_headless_capability()

    def _detect_headless_capability(self) -> bool:
        """Detect if we can use headless rendering (LibreOffice + pdf2image)."""
        if not convert_from_path:
            return False
        
        # Check for LibreOffice/soffice executable
        candidates = ["soffice", "libreoffice"]
        if platform.system() == "Windows":
            # Common Windows paths
            candidates.extend([
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            ])
        
        for candidate in candidates:
            if shutil.which(candidate):
                logger.info("Headless rendering available using: %s", candidate)
                return True
        
        logger.info("Headless rendering not available (LibreOffice not found)")
        return False

    def capture(self, pptx_path: Path, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        
        if self._mock_mode:
            logger.info("Creating placeholder screenshot (mock mode)")
            return self._create_placeholder(destination, pptx_path)
        
        # Try headless rendering first (server-friendly)
        if self._headless_mode:
            logger.info("Attempting headless screenshot using LibreOffice")
            return self._capture_headless(pptx_path, destination)
        
        # Fall back to GUI-based capture
        if mss:
            logger.info("Attempting GUI-based screenshot capture")
            return self._capture_with_viewer(pptx_path, destination)
        
        # No screenshot method available - fail
        raise RuntimeError(
            "No screenshot capture method available. "
            "Install LibreOffice + pdf2image for headless mode, or mss for GUI mode. "
            "See HEADLESS_SETUP.md for installation instructions."
        )

    def _capture_headless(self, pptx_path: Path, destination: Path) -> Path:
        """Convert PPTX to image using headless LibreOffice and pdf2image."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Convert PPTX to PDF using LibreOffice headless
            logger.info("Converting PPTX to PDF...")
            soffice_cmd = self._get_soffice_command()
            
            result = subprocess.run(
                [
                    soffice_cmd,
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", str(tmpdir_path),
                    str(pptx_path)
                ],
                check=False,
                capture_output=True,
                timeout=30,
            )
            
            if result.returncode != 0:
                error_msg = f"LibreOffice conversion failed with code {result.returncode}"
                if result.stderr:
                    error_msg += f"\nStderr: {result.stderr.decode('utf-8', errors='replace')}"
                if result.stdout:
                    error_msg += f"\nStdout: {result.stdout.decode('utf-8', errors='replace')}"
                raise RuntimeError(error_msg)
            
            # Find the generated PDF
            pdf_path = tmpdir_path / f"{pptx_path.stem}.pdf"
            if not pdf_path.exists():
                # List all files in tmpdir for debugging
                files = list(tmpdir_path.iterdir())
                raise FileNotFoundError(
                    f"PDF not generated at {pdf_path}. "
                    f"Files in temp dir: {[f.name for f in files]}"
                )
            
            # Convert first page of PDF to image
            logger.info("Converting PDF to image...")
            images = convert_from_path(
                str(pdf_path),
                first_page=1,
                last_page=1,
                dpi=150,  # Balance between quality and file size
            )
            
            if not images:
                raise ValueError("No images generated from PDF")
            
            # Save the first page
            images[0].save(destination, "PNG")
            logger.info("Headless screenshot saved to: %s", destination.name)
            
        return destination

    def _get_soffice_command(self) -> str:
        """Get the soffice/LibreOffice executable path."""
        candidates = ["soffice", "libreoffice"]
        if platform.system() == "Windows":
            candidates.extend([
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            ])
        
        for candidate in candidates:
            path = shutil.which(candidate)
            if path:
                return path
        
        raise FileNotFoundError("LibreOffice (soffice) executable not found")

    def _capture_with_viewer(self, pptx_path: Path, destination: Path) -> Path:
        """Legacy GUI-based screenshot capture using viewer and mss."""
        logger.info("Opening presentation: %s", pptx_path.name)
        process = self._viewer.launch(pptx_path)
        try:
            logger.info("Waiting %.1f seconds for viewer to open...", self._config.viewer_launch_delay_seconds)
            time.sleep(self._config.viewer_launch_delay_seconds)
            
            self._bring_viewer_to_front(pptx_path)
            time.sleep(self._config.focus_delay_seconds)
            
            logger.info("Capturing screenshot...")
            with mss.mss() as sct:
                monitor = self._select_monitor(sct)
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                img.save(destination)
            logger.info("Screenshot saved to: %s", destination.name)
        finally:
            self._viewer.close(process)
        return destination

    def _bring_viewer_to_front(self, pptx_path: Path) -> None:
        """Platform-specific window activation."""
        system = platform.system().lower()
        try:
            if "windows" in system:
                # Windows: Use PowerShell to bring window to front
                stem = pptx_path.stem
                script = f"""$wshell = New-Object -ComObject wscript.shell; 
                $wshell.AppActivate('{stem}')"""
                subprocess.run(["powershell", "-Command", script], capture_output=True, timeout=2)
            elif "darwin" in system:
                # macOS: Use AppleScript or similar if needed
                pass
        except Exception as error:  # pylint: disable=broad-except
            logger.debug("Could not activate viewer window: %s", error)

    def _select_monitor(self, sct: "mss.mss") -> dict:  # type: ignore[name-defined]
        """Select monitor to capture - prefer configured region or primary monitor."""
        region = self._parse_region(self._config.capture_region)
        if region:
            left, top, width, height = region
            return {"left": left, "top": top, "width": width, "height": height}
        
        # Use primary monitor (index 1 in mss, 0 is all monitors combined)
        monitors = sct.monitors
        if len(monitors) > 1:
            return monitors[1]
        return monitors[0]

    @staticmethod
    def _parse_region(region_str: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
        if not region_str:
            return None
        parts = region_str.split(",")
        if len(parts) != 4:
            return None
        try:
            return tuple(int(part.strip()) for part in parts)  # type: ignore[return-value]
        except ValueError:
            return None

    def _create_placeholder(self, destination: Path, pptx_path: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (1280, 720), color=(240, 240, 240))
        draw = ImageDraw.Draw(image)
        text = f"Placeholder screenshot\n{pptx_path.name}"
        try:
            font = ImageFont.load_default()
        except Exception:  # pragma: no cover - Pillow always provides default font but we stay defensive
            font = None  # type: ignore[assignment]
        draw.multiline_text((40, 40), text, fill=(80, 80, 80), font=font, spacing=10)
        image.save(destination)
        return destination