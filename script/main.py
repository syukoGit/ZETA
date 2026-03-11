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
from phase_resolver import refresh_phase, get_current_phase
from utils.market_status import get_market_status
from utils.timing import get_wait_time, countdown_display

logger = get_logger(__name__)


def _recover_previous_state(dbTools: DBTools):
    previous_reporting = None
    last_review_reporting = None

    try:
        last_review_runs = dbTools.get_filtered_runs(
            trigger_type="review", status="completed", limit=1
        )
        if last_review_runs:
            review_run = dbTools.get_run_by_id(last_review_runs[0].id)
            if review_run:
                for msg in review_run.messages:
                    for tc in msg.tool_calls:
                        if tc.tool_name == "close_review" and tc.output_payload:
                            last_review_reporting = tc.output_payload
                            break
                    if last_review_reporting:
                        break
    except Exception as e:
        logger.warning("Could not restore last_review_reporting from DB: %s", e)

    try:
        last_llm_runs = dbTools.get_filtered_runs(
            trigger_type="llm_call", status="completed", limit=1
        )
        if last_llm_runs:
            llm_run = dbTools.get_run_by_id(last_llm_runs[0].id)
            if llm_run:
                for msg in llm_run.messages:
                    for tc in msg.tool_calls:
                        if tc.tool_name == "close_run" and tc.output_payload:
                            previous_reporting = tc.output_payload.get("summary")
                            break
                    if previous_reporting:
                        break
    except Exception as e:
        logger.warning("Could not restore previous_reporting from DB: %s", e)

    logger.info(
        "Restored session state: previous_reporting=%s, last_review=%s",
        "yes" if previous_reporting else "no",
        "yes" if last_review_reporting else "no",
    )

    return previous_reporting, last_review_reporting


async def main():
    ib = None
    db = None
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

    previous_reporting, last_review_reporting = _recover_previous_state(dbTools)

    dry_run = config().dry_run
    if dry_run:
        logger.info("Running in dry-run mode. No real trades will be executed.")

    try:
        ib = await init_ib_connection(dry_run)

        run_counter = 0
        while True:
            await refresh_phase()
            phase_cfg = get_current_phase().config

            if any(
                market_status.get("status") == "OPEN"
                for market_status in get_market_status(
                    datetime.now(timezone.utc)
                ).values()
            ):
                run_counter += 1
            else:
                run_counter = 0  # Reset counter if markets are closed

            if run_counter >= phase_cfg.review.runs_before_review:
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
                    if time_before_next_run_s is not None:
                        time_before_next_run = max(
                            phase_cfg.run_interval.min,
                            min(
                                phase_cfg.run_interval.max, int(time_before_next_run_s)
                            ),
                        )
                    else:
                        time_before_next_run = phase_cfg.run_interval.min

                    logger.info(
                        "LLM call completed (%s). Summary: %s",
                        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        previous_reporting,
                    )
                except Exception as e:
                    logger.error("Error during LLM call: %s", e)
                    previous_reporting = {}
                    time_before_next_run = phase_cfg.run_interval.min

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
