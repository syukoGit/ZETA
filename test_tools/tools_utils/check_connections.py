import asyncio
import os
import time
from typing import Any, Tuple
from uuid import UUID

from test_tools.tools_utils.display import fail, header, info, ok


# Database test
def test_database() -> bool:
    header("Database Connection Test")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        fail("DATABASE_URL environment variable is not set.")
        return False

    masked = db_url
    try:
        from urllib.parse import urlparse

        parsed = urlparse(db_url)
        if parsed.password:
            masked = db_url.replace(parsed.password, "****")
    except Exception:
        pass
    info(f"Connection string: {masked}")

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url, connect_args={"connect_timeout": 5})
        start = time.perf_counter()

        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            version = result.scalar()
            elapsed = (time.perf_counter() - start) * 1000

        ok(f"Connected in {elapsed:.0f} ms")
        ok(f"Server version: {version}")
    except Exception as exc:
        fail(f"Connection failed: {exc}")
        return False

    try:
        from db.database import DatabaseManager

        db = DatabaseManager(db_url)
        with db.get_session() as session:
            from sqlalchemy import inspect as sa_inspect

            inspector = sa_inspect(session.bind)
            tables = inspector.get_table_names()
            if tables:
                ok(f"Tables found: {', '.join(sorted(tables))}")
            else:
                info("No application tables found (database may need initialization).")
    except Exception as exc:
        fail(f"Could not inspect tables: {exc}")
        return False

    ok("Database test PASSED")
    return True


def init_database(trigger_type: str) -> Tuple[Any, UUID, UUID] | None:
    header("Database Initialization")

    try:
        from db.database import init_db

        db = init_db()
        ok("Database initialized successfully.")
    except Exception as exc:
        fail(f"Database initialization failed: {exc}")
        return

    try:
        from db.db_tools import DBTools

        db_tools = DBTools()

        run_id = db_tools.start_run(trigger_type, "manual", "n/a")
        message_id = db_tools.add_message(
            run_id, "system", f"{trigger_type} interactive session"
        )
        ok(f"Test run created (run_id={run_id}, message_id={message_id}).")

        return db, run_id, message_id
    except Exception as exc:
        fail(f"Could not create test run/message: {exc}")
        return


# IBKR test
async def test_ibkr() -> bool:
    header("IBKR Connection Test")

    try:
        from config import config

        ibkr = config().ibkr
        host = ibkr.host
        port = ibkr.port
        client_id = ibkr.client_id
    except Exception as exc:
        fail(f"Could not read IBKR config: {exc}")
        return False

    info(f"Connecting to IBKR at {host}:{port} with client_id={client_id}")

    try:
        from ib_async import IB

        ib = IB()
        start = time.perf_counter()
        await ib.connectAsync(host, port, client_id)
        elapsed = (time.perf_counter() - start) * 1000

        if not ib.isConnected():
            fail("IBKR connection failed: unknown error.")
            return False

        ok(f"Connected in {elapsed:.0f} ms")

        # Gather basic account info
        managed = ib.managedAccounts()
        if managed:
            ok(f"Managed accounts: {', '.join(managed)}")

        server_version = ib.client.serverVersion()
        ok(f"Server version: {server_version}")

        # Cleanly disconnect
        ib.disconnect()
        ok("Disconnected gracefully")

    except ConnectionRefusedError:
        fail(f"Connection refused — is TWS / IB Gateway running on {host}:{port}?")
        return False
    except asyncio.TimeoutError:
        fail(
            f"Connection timed out after 15 s — is TWS / IB Gateway reachable at {host}:{port}?"
        )
        return False
    except Exception as exc:
        fail(f"Connection failed: {exc}")
        return False

    ok("IBKR test PASSED")
    return True


async def init_ibkr() -> None:
    header("IBKR Initialization")

    try:
        from config import config

        ibkr = config().ibkr
        host = ibkr.host
        port = ibkr.port
        client_id = ibkr.client_id
    except Exception as exc:
        fail(f"Could not read IBKR config: {exc}")
        return

    info(f"Connecting to IBKR at {host}:{port} with client_id={client_id}")

    try:
        from ibkr.ibTools import init_ib_connection

        ib = await init_ib_connection(dry_run=False)
        if ib is None:
            fail("IBKR initialization failed.")
        else:
            ok("Connected successfully")
    except Exception as exc:
        fail(f"IBKR initialization failed: {exc}")
