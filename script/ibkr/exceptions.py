"""Custom exceptions for the IB Watchdog layer."""


class IBConnectionUnavailableError(Exception):
    """Raised when the IB connection is not available after waiting."""


class IBTransientError(Exception):
    """Raised on transient IB errors (e.g. code 162) that may be retried."""

    def __init__(self, message: str, error_code: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
