import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv
import nest_asyncio
from ibkr.ibTools import init_ib_connection
from db.database import init_db
from db.db_tools import DBTools
from config import config, start_config_watcher
from logger import setup_logging, get_logger
from llm.llm_call import run_llm_call, run_llm_review_call
from utils.market_status import get_market_status
from utils.timing import get_wait_time, countdown_display

logger = get_logger(__name__)


async def main():
    ib = None
    db = None
    previous_reporting = None
    last_review_reporting = None
    time_before_next_run = None

    load_dotenv()
    setup_logging()
    start_config_watcher()

    try:
        logger.info("Initializing database...")
        db = init_db()
        db.create_tables()
    except Exception as e:
        logger.error("Error initializing database: %s", e)
        return

    dbTools = DBTools()
    logger.info("Database initialized and session started.")

    dry_run = config().dry_run
    if dry_run:
        logger.info("Running in dry-run mode. No real trades will be executed.")

    try:
        ib = await init_ib_connection(dry_run)

        run_counter = config().review.every_n_trades
        while True:
            if any(
                market_status.get("status") == "OPEN"
                for market_status in get_market_status(
                    datetime.now(timezone.utc)
                ).values()
            ):
                run_counter += 1
            else:
                run_counter = 0  # Reset counter if markets are closed

            if run_counter >= config().review.every_n_trades:
                run_counter = 0
                try:
                    logger.info(
                        "Running review... (%s)",
                        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    )

                    last_review_reporting = await run_llm_review_call(
                        dbTools, last_review_reporting
                    )

                    logger.info(
                        "Review reporting (%s): %s",
                        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        last_review_reporting,
                    )

                    time_before_next_run = 1
                except Exception as e:
                    logger.error("Error during review LLM call: %s", e)
                    last_review_reporting = None
                    time_before_next_run = 1
            else:
                try:
                    logger.info(
                        "LLM call... (%s)",
                        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    )

                    (summary, time_before_next_run_s) = await run_llm_call(
                        dbTools, previous_reporting, last_review_reporting
                    )

                    previous_reporting = summary
                    time_before_next_run = (
                        time_before_next_run_s
                        if time_before_next_run_s is not None
                        else config().default_wait_seconds
                    )

                    logger.info(
                        "LLM call completed (%s). Summary: %s",
                        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        previous_reporting,
                    )
                except Exception as e:
                    logger.error("Error during LLM call: %s", e)
                    previous_reporting = {}
                    time_before_next_run = config().default_wait_seconds

                logger.info(
                    "Reporting (%s):",
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                )
                logger.debug("Reporting data: %s", previous_reporting)

                time_before_next_run = get_wait_time(time_before_next_run)

            await countdown_display(time_before_next_run)
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.error("Error in main: %s", e, exc_info=True)
    finally:
        logger.info("Disconnecting IB...")
        if ib and ib.isConnected():
            ib.disconnect()


if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
