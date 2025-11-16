"""Centralized logging configuration for slidegen."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


# Custom log level for console progress messages
PROGRESS = 25  # Between INFO (20) and WARNING (30)
logging.addLevelName(PROGRESS, "PROGRESS")


class ProgressFilter(logging.Filter):
    """Filter that only allows PROGRESS level messages."""
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == PROGRESS


class ExcludeProgressFilter(logging.Filter):
    """Filter that excludes PROGRESS level messages."""
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno != PROGRESS


def progress(logger: logging.Logger, message: str, *args, **kwargs) -> None:
    """Log a progress message that will be shown to the user on console."""
    if logger.isEnabledFor(PROGRESS):
        logger._log(PROGRESS, message, args, **kwargs)


# Add progress method to Logger class
logging.Logger.progress = progress  # type: ignore[attr-defined]


def setup_logging(log_file_path: Optional[Path] = None, console_level: int = PROGRESS) -> None:
    """
    Configure logging for a run.
    
    Sets up two handlers:
    1. File handler - logs everything at INFO level and above to the run's log file
    2. Console handler - only shows PROGRESS level messages to the user
    
    Args:
        log_file_path: Path to the log file for this run. If None, only console logging is set up.
        console_level: Minimum level to show on console (default: PROGRESS for user-facing messages)
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything, handlers will filter
    
    # Remove any existing handlers
    root_logger.handlers.clear()
    
    # Create formatters
    file_formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_formatter = logging.Formatter(
        fmt='[SlideGen] %(message)s'
    )
    
    # Set up file handler if log file path is provided
    if log_file_path:
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(file_formatter)
        file_handler.addFilter(ExcludeProgressFilter())  # Don't duplicate progress in file
        root_logger.addHandler(file_handler)
    
    # Set up console handler for user-facing progress messages
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(ProgressFilter())  # Only show PROGRESS messages
    root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)


def log_ai_request(logger: logging.Logger, operation: str, prompt: str,  reference_image: Optional[Path] = None, previous_image: Optional[Path] = None, model: Optional[str] = None) -> None:
    """Log an AI request with clear formatting."""
    logger.info("=" * 80)
    logger.info("AI REQUEST: %s", operation)

    if reference_image:
        logger.info("Reference Image: %s", reference_image)
    
    if previous_image:
        logger.info("Previous Image: %s", previous_image)

    if model:
        logger.info("Model: %s", model)
    logger.info("-" * 80)
    logger.info("PROMPT:\n%s", prompt)
    logger.info("=" * 80)


def log_ai_response(logger: logging.Logger, operation: str, response: str, request_id: Optional[str] = None) -> None:
    """Log an AI response with clear formatting."""
    logger.info("=" * 80)
    logger.info("AI RESPONSE: %s", operation)
    if request_id:
        logger.info("Request ID: %s", request_id)
    logger.info("-" * 80)
    logger.info("RESPONSE:\n%s", response)
    logger.info("=" * 80)
