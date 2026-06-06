"""Structured logging setup for the novel writer agent."""

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
    log_dir: str | Path = "logs",
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> logging.Logger:
    """Configure structured logging with rotating file + console output.

    Args:
        log_dir: Directory for log files.
        level: Logging level.
        max_bytes: Max size per log file before rotation.
        backup_count: Number of backup files to keep.

    Returns:
        Root logger configured for the application.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger("src")
    root_logger.setLevel(level)

    # Clear existing handlers to avoid duplicates on reload
    root_logger.handlers.clear()

    # Formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (INFO+)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    # File handler — all logs
    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Cost log — separate file for cost tracking
    cost_handler = RotatingFileHandler(
        log_dir / "cost.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    cost_handler.setLevel(logging.INFO)
    cost_handler.setFormatter(formatter)
    cost_logger = logging.getLogger("src.llm.cost_tracker")
    cost_logger.addHandler(cost_handler)
    cost_logger.propagate = False  # Don't send to root handlers

    # Dedicated error file
    error_handler = RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    root_logger.info("Logging initialized | log_dir=%s | level=%s", log_dir, logging.getLevelName(level))
    return root_logger
