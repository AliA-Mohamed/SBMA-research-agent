"""Centralized logging configuration."""

import logging
import sys
from rich.logging import RichHandler
import config


def setup_logger(name: str = "sbma_agent") -> logging.Logger:
    """Configure and return a logger with both file and console handlers."""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    # File handler
    file_handler = logging.FileHandler(config.LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    # Console handler (rich)
    console_handler = RichHandler(rich_tracebacks=True, show_path=False)
    console_handler.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    logger.addHandler(console_handler)

    return logger
