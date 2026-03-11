import asyncio
from typing import Optional
from ib_async import IB
from logger import get_logger
from config import config

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
    ib_sem = asyncio.Semaphore(5)

    _ = IBTools(ib, ib_sem=ib_sem, dry_run=dry_run)

    return ib


class IBTools:
    _instance: Optional["IBTools"] = None

    ib: IB
    ib_sem: asyncio.Semaphore
    dry_run: bool

    def __new__(cls, ib: IB, *, ib_sem: asyncio.Semaphore, dry_run: bool = True):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.ib = ib
            cls._instance.ib_sem = ib_sem
            cls._instance.dry_run = dry_run
        return cls._instance

    @classmethod
    def get_instance(cls) -> "IBTools":
        if cls._instance is None:
            raise RuntimeError(
                "IBTools has not been initialized. Call IBTools(ib, ib_sem=...) first."
            )
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None
