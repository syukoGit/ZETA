import logging
import re
import sys

import colorlog

from config import config


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

    handler = _ProgressAwareStreamHandler(sys.stdout)
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


_PROGRESS_PREFIX = "\033[32m[PROGRESS]\033[0m"
_PROGRESS_PADDING = (
    " " * 20
)  # Overwrite any leftover characters from a longer previous message
_CLEAR_LINE = "\r" + " " * 200 + "\r"

_current_progress: str | None = None


class _ProgressAwareStreamHandler(logging.StreamHandler):
    """StreamHandler that preserves the in-place progress line across normal log emissions."""

    def emit(self, record: logging.LogRecord) -> None:
        if _current_progress is not None:
            self.stream.write(_CLEAR_LINE)
        super().emit(record)
        if _current_progress is not None:
            self.stream.write(
                f"\r{_PROGRESS_PREFIX} {_current_progress}{_PROGRESS_PADDING}"
            )
            self.stream.flush()


def log_progress(message: str) -> None:
    global _current_progress
    _current_progress = message
    sys.stdout.write(f"\r{_PROGRESS_PREFIX} {message}{_PROGRESS_PADDING}")
    sys.stdout.flush()


def log_progress_end() -> None:
    global _current_progress
    _current_progress = None
    sys.stdout.write("\n")
    sys.stdout.flush()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
