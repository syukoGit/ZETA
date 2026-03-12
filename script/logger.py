import logging
import re
import sys
from datetime import datetime, timezone

import colorlog

from config import config


RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"

_IB_200_RE = re.compile(r"\bError\s+200\b", re.IGNORECASE)


class _DropIB200UnknownContractFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "ib_async.wrapper" and record.name != "ib_async.ib":
            return True

        msg = record.getMessage()
        is_error_200 = bool(_IB_200_RE.search(msg))
        is_error_txt = "Error 200" in msg
        is_unknown_contract = "Unknown contract" in msg

        if is_error_200 or is_error_txt or is_unknown_contract:
            return False
        return True


def setup_logging() -> None:
    """Configure root logging based on config.json."""
    level = logging.DEBUG if config().debug_print else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicates if called multiple times
    if root.handlers:
        root.handlers.clear()

    handler = _DynamicAwareStreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.addFilter(_DropIB200UnknownContractFilter())
    formatter = colorlog.ColoredFormatter(
        fmt="%(asctime)s %(log_color)s[%(levelname)s]%(reset)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    logging.getLogger("ib_async").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


_CLEAR_LINE = "\r" + " " * 200 + "\r"

_current_progress: str | None = None


class _DynamicAwareStreamHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        if _current_progress is not None:
            self.stream.write(_CLEAR_LINE)
        super().emit(record)
        if _current_progress is not None:
            self.stream.write(f"\r{_current_progress}{RESET}")
            self.stream.flush()


def dynamic_log(message: str, *args) -> None:
    global _current_progress
    formatted = message % args if args else message
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _current_progress = f"{timestamp} {formatted}"
    sys.stdout.write(f"\r{timestamp} {formatted}{RESET}")
    sys.stdout.flush()


def dynamic_log_end() -> None:
    global _current_progress
    _current_progress = None
    sys.stdout.write("\n")
    sys.stdout.flush()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
