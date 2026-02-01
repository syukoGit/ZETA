import asyncio
from typing import Optional
from ib_async import IB

from ibkr.toolArgs import *

async def init_ib_connection(dry_run: bool = True) -> IB:
    ib = IB()
    await ib.connectAsync("127.0.0.1", 7497, clientId=0)

    while not ib.isConnected():
        await asyncio.sleep(0.1)

    ib_sem = asyncio.Semaphore(1)

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
            raise RuntimeError("IBTools has not been initialized. Call IBTools(ib, ib_sem=...) first.")
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None
