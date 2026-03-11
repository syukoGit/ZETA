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
        is_error_txt = "ib_async.wrapper: Error 200" in msg
        is_unknown_contract = "ib_async.ib: Unknown contract" in msg

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

    handler = logging.StreamHandler(sys.stdout)
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


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (convention: __name__)."""
    return logging.getLogger(name)
