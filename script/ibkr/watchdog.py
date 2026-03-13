from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import AsyncIterator, Awaitable, Callable, Optional, Set, TypeVar

from ib_async import IB

from config import config
from ibkr.exceptions import IBConnectionUnavailableError, IBTransientError
from logger import get_logger

T = TypeVar("T")

logger = get_logger("ibkr.watchdog")


class ConnectionState(Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    FARMS_PENDING = "FARMS PENDING"
    STABLE = "STABLE"
    DEGRADED = "DEGRADED"


# IB error codes handled by the watchdog
_CODE_CONNECTIVITY_LOST = 1100
_CODE_CONNECTIVITY_RESTORED_DATA_LOST = 1101
_CODE_CONNECTIVITY_RESTORED_DATA_OK = 1102
_CODE_MARKET_DATA_FARM_DISCONNECTED = 2103
_CODE_MARKET_DATA_FARM_CONNECTED = 2104
_CODE_HMDS_DATA_FARM_CONNECTED = 2106
_CODE_HISTORICAL_DATA_ERROR = 162


class IBWatchdog:
    """Monitors and manages IB connection lifecycle."""

    def __init__(self, ib: IB, *, ib_sem: asyncio.Semaphore) -> None:
        self._ib = ib
        self._ib_sem = ib_sem
        self._state = ConnectionState.DISCONNECTED
        self._farms_ready = asyncio.Event()
        self._stable_event = asyncio.Event()
        self._stable_since: Optional[datetime] = None
        self._shutdown_event = asyncio.Event()
        self._disconnected_since: Optional[datetime] = None
        self._prolonged_disconnect_logged = False

        # Background tasks
        self._reconnect_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._stabilization_task: Optional[asyncio.Task] = None

        # Reconnect bookkeeping
        self._consecutive_failures = 0

        # Track recent IB error codes for retry detection
        self._recent_error_codes: list[int] = []

        # Register IB error callback
        self._ib.errorEvent += self._on_ib_error
        self._ib.disconnectedEvent += self._on_disconnected

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def stable_since(self) -> Optional[datetime]:
        return self._stable_since

    def start(self) -> None:
        """Start background monitoring tasks (reconnect + heartbeat)."""
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.ensure_future(self._reconnect_loop())

        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())

        logger.info("Background tasks started")

    async def wait_until_stable(self, timeout: float = 120.0) -> bool:
        """Block until the connection is STABLE. Returns False on timeout."""
        if self._state == ConnectionState.STABLE:
            return True

        self._stable_event.clear()

        try:
            await asyncio.wait_for(self._stable_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def shutdown(self) -> None:
        """Gracefully stop all background tasks."""
        logger.info("Shutting down...")
        self._shutdown_event.set()
        for task in (
            self._reconnect_task,
            self._heartbeat_task,
            self._stabilization_task,
        ):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._ib.errorEvent -= self._on_ib_error
        self._ib.disconnectedEvent -= self._on_disconnected

        logger.info("Shutdown IBKR Watchdog complete")

    def mark_stable(self) -> None:
        """Manually transition to STABLE (used after initial connection)."""
        self._transition(ConnectionState.STABLE)

    @asynccontextmanager
    async def guarded(self) -> AsyncIterator[None]:
        """Context manager that blocks until STABLE, then acquires the semaphore.

        Raises IBConnectionUnavailableError if the connection does not
        become STABLE within the configured timeout.
        """
        timeout = config().ibkr.watchdog.guard_timeout

        if self._state != ConnectionState.STABLE:
            logger.debug(
                "guarded() waiting for STABLE (current=%s, timeout=%ds)",
                self._state.value,
                timeout,
            )

            self._stable_event.clear()

            try:
                await asyncio.wait_for(self._stable_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                raise IBConnectionUnavailableError(
                    f"IB connection not available (state={self._state.value}) "
                    f"after waiting {timeout}s"
                )

        async with self._ib_sem:
            yield

    async def request_with_retry(
        self,
        coro_factory: Callable[[], Awaitable[T]],
        *,
        retry_on_codes: Set[int] | None = None,
    ) -> T:
        if retry_on_codes is None:
            retry_on_codes = {_CODE_HISTORICAL_DATA_ERROR}

        wd_cfg = config().ibkr.watchdog
        max_attempts = wd_cfg.retry_max_attempts
        delay = wd_cfg.retry_initial_delay

        last_exc: BaseException | None = None
        for attempt in range(1, max_attempts + 1):
            # Clear recent error codes before attempting
            self._recent_error_codes.clear()
            try:
                async with self.guarded():
                    return await coro_factory()
            except IBTransientError as exc:
                last_exc = exc
                if exc.error_code not in retry_on_codes:
                    raise
            except Exception as exc:
                # Check if a retryable IB error appeared during execution
                if not (retry_on_codes & set(self._recent_error_codes)):
                    raise
                last_exc = exc

            if attempt < max_attempts:
                logger.warning(
                    "Retrying request (attempt %d/%d) after %ds — last error: %s",
                    attempt,
                    max_attempts,
                    delay,
                    last_exc,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, wd_cfg.reconnect_max_backoff)

        logger.error(
            "Request failed after %d attempts: %s",
            max_attempts,
            last_exc,
        )
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _transition(self, new_state: ConnectionState) -> None:
        old = self._state
        if old == new_state:
            return
        self._state = new_state
        logger.info("State transition: %s -> %s", old.value, new_state.value)

        if new_state == ConnectionState.STABLE:
            self._stable_since = datetime.now(timezone.utc)
            self._farms_ready.set()
            self._stable_event.set()
            self._consecutive_failures = 0
            self._disconnected_since = None
            self._prolonged_disconnect_logged = False
        else:
            self._stable_since = None
            self._farms_ready.clear()
            self._stable_event.clear()

        if new_state == ConnectionState.DISCONNECTED:
            if self._disconnected_since is None:
                self._disconnected_since = datetime.now(timezone.utc)
            # Wake up the reconnect loop
            self._farms_ready.clear()

    # ------------------------------------------------------------------
    # IB event handlers
    # ------------------------------------------------------------------

    def _on_ib_error(
        self, reqId: int, errorCode: int, errorString: str, contract: object
    ) -> None:
        logger.debug(
            "IB error reqId=%s code=%d msg=%s state=%s",
            reqId,
            errorCode,
            errorString,
            self._state.value,
        )

        if errorCode == _CODE_CONNECTIVITY_LOST:
            logger.warning("Connectivity lost (1100): %s", errorString)
            self._cancel_stabilization()
            self._transition(ConnectionState.DISCONNECTED)

        elif errorCode == _CODE_CONNECTIVITY_RESTORED_DATA_LOST:
            logger.info(
                "Connectivity restored, data lost (1101): %s",
                errorString,
            )
            self._transition(ConnectionState.CONNECTING)

        elif errorCode == _CODE_CONNECTIVITY_RESTORED_DATA_OK:
            logger.info(
                "Connectivity restored, data maintained (1102): %s",
                errorString,
            )
            self._transition(ConnectionState.FARMS_PENDING)
            self._start_stabilization()

        elif errorCode == _CODE_MARKET_DATA_FARM_DISCONNECTED:
            logger.warning(
                "Market data farm disconnected (2103): %s",
                errorString,
            )
            if self._state == ConnectionState.STABLE:
                self._transition(ConnectionState.DEGRADED)

        elif errorCode in (
            _CODE_MARKET_DATA_FARM_CONNECTED,
            _CODE_HMDS_DATA_FARM_CONNECTED,
        ):
            logger.info(
                "Data farm connected (%d): %s",
                errorCode,
                errorString,
            )
            if self._state in (
                ConnectionState.DEGRADED,
                ConnectionState.FARMS_PENDING,
            ):
                self._transition(ConnectionState.FARMS_PENDING)
                self._start_stabilization()

        elif errorCode == _CODE_HISTORICAL_DATA_ERROR:
            logger.warning("Historical data error (162): %s", errorString)
            self._recent_error_codes.append(errorCode)

    def _on_disconnected(self) -> None:
        logger.warning("IB disconnected event received")
        self._cancel_stabilization()
        if self._state != ConnectionState.DISCONNECTED:
            self._transition(ConnectionState.DISCONNECTED)

    # ------------------------------------------------------------------
    # Farm stabilization
    # ------------------------------------------------------------------

    def _start_stabilization(self) -> None:
        """Start (or restart) the farm stabilization delay."""
        self._cancel_stabilization()
        self._stabilization_task = asyncio.ensure_future(self._farm_stabilization())

    def _cancel_stabilization(self) -> None:
        if self._stabilization_task and not self._stabilization_task.done():
            self._stabilization_task.cancel()
            self._stabilization_task = None

    async def _farm_stabilization(self) -> None:
        """Wait for farms to settle after reconnection, then go STABLE."""
        delay = config().ibkr.watchdog.farm_stabilization_delay
        logger.info("Waiting %ds for farm stabilization...", delay)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.debug("Farm stabilization cancelled")
            return

        if not self._ib.isConnected():
            logger.warning("Connection lost during stabilization, aborting")
            self._transition(ConnectionState.DISCONNECTED)
            return

        self._transition(ConnectionState.STABLE)
        logger.info("Farms stabilized — connection is STABLE")

    # ------------------------------------------------------------------
    # Reconnect loop
    # ------------------------------------------------------------------

    async def _reconnect_loop(self) -> None:
        """Background task that reconnects when DISCONNECTED."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(1)

                if self._state != ConnectionState.DISCONNECTED:
                    continue

                if self._ib.isConnected():
                    self._transition(ConnectionState.FARMS_PENDING)
                    self._start_stabilization()
                    continue

                await self._attempt_reconnect()

            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Unexpected error in reconnect loop")
                await asyncio.sleep(5)

    async def _attempt_reconnect(self) -> None:
        """Try to reconnect with exponential backoff."""
        ibkr_cfg = config().ibkr
        wd_cfg = ibkr_cfg.watchdog

        backoff = wd_cfg.reconnect_initial_backoff
        max_backoff = wd_cfg.reconnect_max_backoff
        max_retries = wd_cfg.reconnect_max_retries

        for attempt in range(1, max_retries + 1):
            if self._shutdown_event.is_set():
                return

            self._transition(ConnectionState.CONNECTING)
            logger.warning(
                "Reconnecting (attempt %d/%d, backoff %ds)...",
                attempt,
                max_retries,
                backoff,
            )

            try:
                await asyncio.wait_for(
                    self._ib.connectAsync(
                        ibkr_cfg.host, ibkr_cfg.port, clientId=ibkr_cfg.client_id
                    ),
                    timeout=30.0,
                )

                if self._ib.isConnected():
                    logger.info("Reconnected successfully")
                    self._consecutive_failures = 0
                    self._transition(ConnectionState.FARMS_PENDING)
                    self._start_stabilization()
                    return

            except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as exc:
                logger.error(
                    "Reconnect attempt %d/%d failed: %s",
                    attempt,
                    max_retries,
                    exc,
                )

            if attempt < max_retries:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

        # All retries exhausted
        self._consecutive_failures += 1
        long_pause = 300
        logger.critical(
            "Reconnection failed after %d attempts "
            "(consecutive failure streak: %d). Pausing %ds before retrying.",
            max_retries,
            self._consecutive_failures,
            long_pause,
        )
        self._transition(ConnectionState.DISCONNECTED)
        await asyncio.sleep(long_pause)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Periodic connection health check."""
        last_log = 0.0
        while not self._shutdown_event.is_set():
            try:
                interval = config().ibkr.watchdog.heartbeat_interval
                await asyncio.sleep(interval)

                connected = self._ib.isConnected()

                if not connected and self._state not in (
                    ConnectionState.DISCONNECTED,
                    ConnectionState.CONNECTING,
                ):
                    logger.warning(
                        "Heartbeat detected disconnection (was %s)",
                        self._state.value,
                    )
                    self._cancel_stabilization()
                    self._transition(ConnectionState.DISCONNECTED)

                elif connected and self._state == ConnectionState.STABLE:
                    now = asyncio.get_event_loop().time()
                    if now - last_log >= 300:  # Log every 5 minutes
                        logger.debug("Heartbeat OK — STABLE")
                        last_log = now

                # CRITICAL alert when disconnected for more than 5 minutes
                if (
                    self._disconnected_since is not None
                    and not self._prolonged_disconnect_logged
                ):
                    elapsed = (
                        datetime.now(timezone.utc) - self._disconnected_since
                    ).total_seconds()
                    if elapsed > 300:
                        logger.critical(
                            "Connection lost for %.0f seconds (>5 min). " "State: %s",
                            elapsed,
                            self._state.value,
                        )
                        self._prolonged_disconnect_logged = True

            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Unexpected error in heartbeat loop")
                await asyncio.sleep(5)
