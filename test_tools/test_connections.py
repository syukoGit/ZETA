"""
Test tool to verify connectivity with IBKR (Interactive Brokers) and the PostgreSQL database.

Usage:
    python test_tools/test_connections.py [--db] [--ibkr] [--all]

Flags:
    --db    Test database connection only
    --ibkr  Test IBKR connection only
    --all   Test both (default if no flag provided)
"""

import argparse
import asyncio
import os
import sys
import time

# Ensure the project root and script/ are on sys.path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "script"))

from dotenv import load_dotenv

load_dotenv(os.path.join(_root, ".env"))

# ── Colour helpers (no dependency on colorlog) ──────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}{msg}{RESET}")


def _fail(msg: str) -> None:
    print(f"  {RED}{msg}{RESET}")


def _info(msg: str) -> None:
    print(f"  {CYAN}{msg}{RESET}")


def _header(title: str) -> None:
    print(f"\n{BOLD}{YELLOW}{'═' * 50}")
    print(f"  {title}")
    print(f"{'═' * 50}{RESET}")


# ── Database test ────────────────────────────────────────────────────────
def test_database() -> bool:
    """Test PostgreSQL connectivity via SQLAlchemy."""
    _header("Database Connection Test")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        _fail("DATABASE_URL environment variable is not set.")
        return False

    # Mask password for display
    masked = db_url
    try:
        from urllib.parse import urlparse

        parsed = urlparse(db_url)
        if parsed.password:
            masked = db_url.replace(parsed.password, "****")
    except Exception:
        pass
    _info(f"Connection string: {masked}")

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
        start = time.perf_counter()

        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            version = result.scalar()
            elapsed = (time.perf_counter() - start) * 1000

        _ok(f"Connected in {elapsed:.0f} ms")
        _ok(f"Server version: {version}")

    except Exception as exc:
        _fail(f"Connection failed: {exc}")
        return False

    # Check that application tables exist
    try:
        from db.database import DatabaseManager

        db = DatabaseManager(db_url)
        with db.get_session() as session:
            from sqlalchemy import inspect as sa_inspect

            inspector = sa_inspect(session.bind)
            tables = inspector.get_table_names()
            if tables:
                _ok(f"Tables found: {', '.join(sorted(tables))}")
            else:
                _info("No application tables found (database may need initialization).")

    except Exception as exc:
        _fail(f"Could not inspect tables: {exc}")
        return False

    _ok("Database test PASSED")
    return True


# ── IBKR test ────────────────────────────────────────────────────────────
async def _test_ibkr_async() -> bool:
    """Test Interactive Brokers TWS / Gateway connectivity."""
    _header("IBKR Connection Test")

    try:
        from config import config

        ibkr = config().ibkr
        host = ibkr.host
        port = ibkr.port
        client_id = ibkr.client_id
    except Exception as exc:
        _fail(f"Could not read IBKR config: {exc}")
        return False

    _info(f"Target: {host}:{port}  (clientId={client_id})")

    try:
        from ib_async import IB

        ib = IB()
        start = time.perf_counter()
        await ib.connectAsync(host, port, clientId=client_id, timeout=15)
        elapsed = (time.perf_counter() - start) * 1000

        if not ib.isConnected():
            _fail("connectAsync returned but IB is not connected.")
            return False

        _ok(f"Connected in {elapsed:.0f} ms")

        # Gather basic account info
        managed = ib.managedAccounts()
        if managed:
            _ok(f"Managed accounts: {', '.join(managed)}")

        server_version = ib.client.serverVersion()
        _ok(f"Server version: {server_version}")

        # Cleanly disconnect
        ib.disconnect()
        _ok("Disconnected gracefully")

    except ConnectionRefusedError:
        _fail(f"Connection refused — is TWS / IB Gateway running on {host}:{port}?")
        return False
    except asyncio.TimeoutError:
        _fail(f"Connection timed out after 15 s — is TWS / IB Gateway reachable at {host}:{port}?")
        return False
    except Exception as exc:
        _fail(f"Connection failed: {exc}")
        return False

    _ok("IBKR test PASSED")
    return True


def test_ibkr() -> bool:
    return asyncio.run(_test_ibkr_async())


# ── Main ─────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Test IBKR and database connectivity.")
    parser.add_argument("--db", action="store_true", help="Test database connection only")
    parser.add_argument("--ibkr", action="store_true", help="Test IBKR connection only")
    parser.add_argument("--all", action="store_true", help="Test both (default)")
    args = parser.parse_args()

    run_all = args.all or (not args.db and not args.ibkr)

    results: dict[str, bool] = {}

    if run_all or args.db:
        results["Database"] = test_database()

    if run_all or args.ibkr:
        results["IBKR"] = test_ibkr()

    # Summary
    _header("Summary")
    all_passed = True
    for name, passed in results.items():
        if passed:
            _ok(f"{name}: OK")
        else:
            _fail(f"{name}: FAILED")
            all_passed = False

    print()
    if all_passed:
        print(f"{GREEN}{BOLD}All connection tests passed.{RESET}")
    else:
        print(f"{RED}{BOLD}Some connection tests failed.{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
