from tools_utils.init import init

init()

import argparse
import asyncio

from test_tools.tools_utils.check_connections import test_database, test_ibkr
from test_tools.tools_utils.display import *


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Test IBKR and database connectivity.")
    parser.add_argument(
        "--db", action="store_true", help="Test database connection only"
    )
    parser.add_argument("--ibkr", action="store_true", help="Test IBKR connection only")
    parser.add_argument("--all", action="store_true", help="Test both (default)")
    args = parser.parse_args()

    run_all = args.all or (not args.db and not args.ibkr)

    results: dict[str, bool] = {}

    if run_all or args.db:
        results["Database"] = test_database()

    if run_all or args.ibkr:
        results["IBKR"] = await test_ibkr()

    # Summary
    header("Summary")
    all_passed = True
    for name, passed in results.items():
        if passed:
            ok(f"{name}: OK")
        else:
            fail(f"{name}: FAILED")
            all_passed = False

    print()
    if all_passed:
        print(f"{GREEN}{BOLD}All connection tests passed.{RESET}")
    else:
        print(f"{RED}{BOLD}Some connection tests failed.{RESET}")


if __name__ == "__main__":
    asyncio.run(_main())
