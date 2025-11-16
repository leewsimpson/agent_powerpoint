from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .logging_config import get_logger

import pymupdf

logger = get_logger(__name__)


class ScreenshotService:
    def __init__(self, mock_mode: bool) -> None:
        self._mock_mode = mock_mode

    def capture(self, pptx_path: Path, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info("Capturing screenshot for: %s", pptx_path)
        logger.info("Destination: %s", destination)
        
        if self._mock_mode:
            logger.info("Using mock mode - creating placeholder screenshot")
            return self._create_placeholder(destination, pptx_path)
        
        logger.info("Using headless LibreOffice + PyMuPDF conversion")
        return self._capture_headless(pptx_path, destination)

    def _capture_headless(self, pptx_path: Path, destination: Path) -> Path:
        """Convert PPTX to image using headless LibreOffice and PyMuPDF."""
        logger.info("Starting headless conversion process")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            logger.info("Temporary directory: %s", tmpdir_path)

            # Convert PPTX to PDF using LibreOffice headless
            logger.info("Step 1: Converting PPTX to PDF using LibreOffice...")
            soffice_cmd = self._get_soffice_command()
            logger.info("LibreOffice command: %s", soffice_cmd)

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
                    stderr_text = result.stderr.decode('utf-8', errors='replace')
                    error_msg += f"\nStderr: {stderr_text}"
                    logger.error("LibreOffice stderr: %s", stderr_text)
                if result.stdout:
                    stdout_text = result.stdout.decode('utf-8', errors='replace')
                    error_msg += f"\nStdout: {stdout_text}"
                    logger.info("LibreOffice stdout: %s", stdout_text)
                logger.error("LibreOffice conversion failed")
                raise RuntimeError(error_msg)
            
            logger.info("LibreOffice conversion successful")

            # Find the generated PDF
            pdf_path = tmpdir_path / f"{pptx_path.stem}.pdf"
            logger.info("Expected PDF path: %s", pdf_path)
            
            if not pdf_path.exists():
                files = list(tmpdir_path.iterdir())
                logger.error("PDF not found. Files in temp dir: %s", [f.name for f in files])
                raise FileNotFoundError(
                    f"PDF not generated at {pdf_path}. Files in temp dir: {[f.name for f in files]}"
                )
            
            logger.info("PDF found: %s (%d bytes)", pdf_path, pdf_path.stat().st_size)

            # Rasterize first page using PyMuPDF
            logger.info("Step 2: Rasterizing first page of PDF with PyMuPDF...")
            doc = pymupdf.open(str(pdf_path))
            try:
                page = doc[0]
                dpi = 150
                zoom = dpi / 72.0
                matrix = pymupdf.Matrix(zoom, zoom)
                logger.info("Rendering at %d DPI (zoom: %.2f)", dpi, zoom)
                
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                pix.save(str(destination))
                logger.info("Screenshot saved: %s (%d bytes)", destination, destination.stat().st_size)
            finally:
                doc.close()

        logger.info("Headless conversion complete")
        return destination

    def _get_soffice_command(self) -> str:
        """Get the soffice/LibreOffice executable path."""
        logger.info("Searching for LibreOffice executable...")
        candidates = ["soffice", "libreoffice"]
        if platform.system() == "Windows":
            candidates.extend([
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            ])
        
        logger.info("Checking candidates: %s", candidates)
        for candidate in candidates:
            path = shutil.which(candidate)
            if path:
                logger.info("Found LibreOffice at: %s", path)
                return path
        
        logger.error("LibreOffice executable not found")
        raise FileNotFoundError("LibreOffice (soffice) executable not found")

    def _create_placeholder(self, destination: Path, pptx_path: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Creating placeholder image: %s", destination)
        
        image = Image.new("RGB", (1280, 720), color=(240, 240, 240))
        draw = ImageDraw.Draw(image)
        text = f"Placeholder screenshot\n{pptx_path.name}"
        try:
            font = ImageFont.load_default()
        except Exception:  # pragma: no cover - Pillow always provides default font but we stay defensive
            font = None  # type: ignore[assignment]
        draw.multiline_text((40, 40), text, fill=(80, 80, 80), font=font, spacing=10)
        image.save(destination)
        logger.info("Placeholder created: %s (%d bytes)", destination, destination.stat().st_size)
        return destination
