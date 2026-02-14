"""
Centralized logging module.
The log level is driven by the "debugPrint" key in config.json:
  - True  → DEBUG (everything is displayed)
  - False → INFO  (only important messages)
"""

import logging
import sys

import colorlog

from config import get as config_get


def setup_logging() -> None:
    """Configure root logging based on config.json."""
    level = logging.DEBUG if config_get("debugPrint", False) else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicates if called multiple times
    if root.handlers:
        root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = colorlog.ColoredFormatter(
        fmt="%(asctime)s %(log_color)s[%(levelname)s]%(reset)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG":    "cyan",
            "INFO":     "green",
            "WARNING":  "yellow",
            "ERROR":    "red",
            "CRITICAL": "bold_red",
        },
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    logging.getLogger("ib_async").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (convention: __name__)."""
    return logging.getLogger(name)
