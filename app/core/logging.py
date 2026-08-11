"""
Centralized logging configuration for ChooNova-Transcribe.
"""

import logging
import sys

def setup_logging(log_level: str = "info") -> None:
    """Configures structured logging format and root log level."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

def get_logger(name: str) -> logging.Logger:
    """Returns a named logger instance."""
    return logging.getLogger(f"choonova.{name}")
