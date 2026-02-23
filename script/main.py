import asyncio
from datetime import datetime, timezone
import json
from dotenv import load_dotenv
import nest_asyncio
from sentence_transformers import SentenceTransformer
from ibkr.ibTools import init_ib_connection
from db.database import init_db
from db.db_tools import DBTools
from config import get
from logger import setup_logging, get_logger
from llm.llm_call import run_llm_call
from utils.timing import get_wait_time, countdown_display

logger = get_logger(__name__)


async def main():
    ib = None
    db = None
    previous_reporting = None

    load_dotenv()
    setup_logging()

    try:
        logger.info("Initializing database...")
        db = init_db()
        db.create_tables()
    except Exception as e:
        logger.error("Error initializing database: %s", e)
        return
    
    dbTools = DBTools()
    logger.info("Database initialized and session started.")

    dry_run = get("dry_run", True)
    if dry_run:
        logger.info("Running in dry-run mode. No real trades will be executed.")

    try:
        ib = await init_ib_connection(dry_run)

        while True:
            try:
                logger.info("LLM call... (%s)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))

                previous_reporting = await run_llm_call(dbTools, previous_reporting)
                if (previous_reporting is None):
                    previous_reporting = {}
                previous_reporting = json.loads(previous_reporting)
                previous_reporting["as_of"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.error("Error during LLM call: %s", e)
                previous_reporting = {"timeBeforeNextRun": get("default_wait_seconds", 600)}
            
            logger.info("Reporting (%s):", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
            logger.debug("Reporting data: %s", previous_reporting)

            base_wait_time = previous_reporting.get("timeBeforeNextRun", get("default_wait_seconds", 600))
            time_before_next_run = get_wait_time(base_wait_time)

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