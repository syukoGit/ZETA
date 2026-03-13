import asyncio
from typing import Awaitable, Callable, Optional, Set, TypeVar, AsyncContextManager

from ib_async import IB

from config import config
from ibkr.watchdog import IBWatchdog
from logger import get_logger

T = TypeVar("T")

logger = get_logger(__name__)


async def init_ib_connection(dry_run: bool = True) -> IB:
    ib = IB()

    ibkr = config().ibkr
    host = ibkr.host
    port = ibkr.port
    client_id = ibkr.client_id

    logger.info("Connecting to IB TWS (%s:%d, clientId=%d)...", host, port, client_id)
    await ib.connectAsync(host, port, clientId=client_id)

    while not ib.isConnected():
        await asyncio.sleep(0.1)

    logger.info("IB TWS connected (dry_run=%s)", dry_run)

    watchdog = IBWatchdog(ib)
    await watchdog._farm_stabilization()
    watchdog.start()

    _ = IBTools(ib, dry_run=dry_run, watchdog=watchdog)

    return ib


class IBTools:
    _instance: Optional["IBTools"] = None

    ib: IB
    dry_run: bool
    watchdog: IBWatchdog

    def __new__(
        cls,
        ib: IB,
        *,
        dry_run: bool = True,
        watchdog: IBWatchdog,
    ):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.ib = ib
            cls._instance.dry_run = dry_run
            cls._instance.watchdog = watchdog
        return cls._instance

    @classmethod
    def get_instance(cls) -> "IBTools":
        if cls._instance is None:
            raise RuntimeError(
                "IBTools has not been initialized. Call init_ib_connection() first."
            )
        return cls._instance

    def guarded(self) -> AsyncContextManager[None]:
        """Delegate to watchdog.guarded() — waits for STABLE + acquires semaphore."""
        return self.watchdog.guarded()

    async def request_with_retry(
        self,
        coro_factory: Callable[[], Awaitable[T]],
        *,
        retry_on_codes: Set[int] | None = None,
    ) -> T:
        """Delegate to watchdog.request_with_retry()."""
        return await self.watchdog.request_with_retry(
            coro_factory, retry_on_codes=retry_on_codes
        )

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None
