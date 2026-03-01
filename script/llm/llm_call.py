import json
from typing import Any, Dict, Tuple
from uuid import UUID
from config import get
from db.db_tools import DBTools
from llm.review_prompt import REVIEW_PROMPT
from llm.tools.history.get_runs_to_review import get_runs_to_review
from llm.tools.utils.get_date_hour_utc_and_markets import get_date_hour_utc_and_markets
from logger import get_logger
from llm.llm_provider import LLM, LLMFactory
from llm.start_prompt import DEFAULT_START_PROMPT
from llm.tools.ibkr.get_cash_balance import get_cash_balance
from llm.tools.ibkr.get_open_trades import get_open_trades
from llm.tools.ibkr.get_positions import get_positions
from utils.json_utils import ExtendedEncoder, is_valid_json

logger = get_logger(__name__)


async def run_llm_call(dbTools: DBTools, previous_reporting: str | None, last_review: str | None, max_loops: int = 20) -> Tuple[Dict, float]:
    llm = LLMFactory.get_provider(get("llm"))
    logger.info("Using LLM provider: %s with model %s", llm.name, llm.model)

    run_id = None

    try:
        run_id = dbTools.start_run("llm_call", llm.name, llm.model)

        # Add initial system prompt to set the context for the LLM
        llm.add_message("run", DEFAULT_START_PROMPT, role="system")
        dbTools.add_message(run_id, "system", DEFAULT_START_PROMPT)

        # Add last reporting summary to the system prompt for context, if available
        summary_message = "PREVIOUS_SUMMARY: " + json.dumps(previous_reporting, cls=ExtendedEncoder) if previous_reporting else "No summary provided."
        llm.add_message("run", summary_message, role="system")
        dbTools.add_message(run_id, "system", summary_message)

        # Add IB snapshot to the system prompt for context
        snapshot_ib = await get_snapshot_ib()
        snapshot_message = "SNAPSHOT_IB: " + json.dumps(snapshot_ib, cls=ExtendedEncoder)
        llm.add_message("run", snapshot_message, role="system")
        dbTools.add_message(run_id, "system", snapshot_message)
        logger.debug("IB snapshot: %s", snapshot_ib)

        # Add last review summary to the system prompt for context, if available
        review_summary_message = "LAST_REVIEW: " + json.dumps(last_review, cls=ExtendedEncoder) if last_review else "No last review summary provided."
        llm.add_message("run", review_summary_message, role="system")
        dbTools.add_message(run_id, "system", review_summary_message)
        logger.debug("Last review summary: %s", review_summary_message)

        loops_count = 0
        finished = False
        
        output_summary = None
        output_time_before_next_run_s = None

        while not finished and loops_count < max_loops:
            loops_count += 1
            (response, tool_calls) = llm.get_response("run")

            llm.add_message("run", response, role="assistant")
            message_id = dbTools.add_message(run_id, "assistant", response)

            logger.debug("Tool calls received: %d", len(tool_calls))

            for tc in tool_calls:
                if llm.is_client_side_tool(tc):
                    (tool_name, payload) = llm.get_tool_calls_info(tc)
                    tool_db_id = dbTools.log_tool_call(message_id, tool_name, payload)

                    try:
                        tool_result = await llm.execute_client_side_tool(tc, message_id)
                        logger.debug("Tool %s result: %s", tool_name, tool_result)

                        llm.add_message("run", tool_result, role="tool_result")
                        dbTools.complete_tool_call(tool_db_id, tool_result)

                        if tool_name == "close_run":
                            logger.info("LLM requested to close the run at iteration %d", loops_count)

                            output_data = json.loads(tool_result)
                            output_summary = output_data["summary"]
                            output_time_before_next_run_s = output_data["time_before_next_run_s"]

                            finished = True
                    except Exception as e:
                        error_message = f"Error executing tool {tool_name}: {str(e)}"
                        llm.add_message("run", error_message, role="tool_result")
                        dbTools.complete_tool_call(tool_db_id, error_message, False)
                        logger.error("Tool %s failed: %s", tool_name, e)
                else:
                    tool_db_id = dbTools.log_tool_call(message_id, tool_name, payload)
                    dbTools.complete_tool_call(tool_db_id, None)

        llm.close_chats()
        if finished:
            dbTools.end_run(run_id)
        else:
            dbTools.end_run(run_id, status="cancelled")

        return output_summary, output_time_before_next_run_s
    except Exception as e:
        logger.error("An error occurred during the LLM call: %s. Closing chat and ending run.", e, exc_info=True)
        llm.close_chats()
        dbTools.end_run(run_id, status="failed")
        return None, None

async def run_llm_review_call(dbTools: DBTools, previous_review: str | None, max_loops: int = 20) -> Dict:
    llm = LLMFactory.get_provider(get("review").get("llm"))
    logger.info("Using LLM provider for review: %s with model %s", llm.name, llm.model)

    review_id = None

    try:
        review_id = dbTools.start_run("review", llm.name, llm.model)

        # Add initial system prompt to set the context for the LLM
        llm.add_message("review", REVIEW_PROMPT, role="system")
        dbTools.add_message(review_id, "system", REVIEW_PROMPT)

        # Add last review summary to the system prompt for context, if available
        summary_message = "PREVIOUS_REVIEW: " + json.dumps(previous_review, cls=ExtendedEncoder) if previous_review else "No previous review summary provided."
        llm.add_message("review", summary_message, role="system")
        dbTools.add_message(review_id, "system", summary_message)

        # Add IB snapshot to the system prompt for context
        snapshot_ib = await get_snapshot_ib()
        snapshot_message = "SNAPSHOT_IB: " + json.dumps(snapshot_ib, cls=ExtendedEncoder)
        llm.add_message("review", snapshot_message, role="system")
        dbTools.add_message(review_id, "system", snapshot_message)
        logger.debug("IB snapshot for review: %s", snapshot_ib)

        # Add all runs since last review to the system prompt for context
        runs_to_review = await get_runs_to_review({})
        runs_message = "RUNS_TO_REVIEW: " + json.dumps(runs_to_review, cls=ExtendedEncoder)
        llm.add_message("review", runs_message, role="system")
        dbTools.add_message(review_id, "system", runs_message)
        logger.debug("Runs to review: %s", runs_message)

        loops_count = 0
        finished = False

        output_review_summary = None

        while not finished and loops_count < max_loops:
            loops_count += 1
            (response, tool_calls) = llm.get_response("review")

            llm.add_message("review", response, role="assistant")
            message_id = dbTools.add_message(review_id, "assistant", response)

            logger.debug("Tool calls received in review: %d", len(tool_calls))

            for tc in tool_calls:
                if llm.is_client_side_tool(tc):
                    (tool_name, payload) = llm.get_tool_calls_info(tc)
                    tool_db_id = dbTools.log_tool_call(message_id, tool_name, payload)

                    try:
                        tool_result = await llm.execute_client_side_tool(tc, message_id)
                        logger.debug("Tool %s result in review: %s", tool_name, tool_result)

                        llm.add_message("review", tool_result, role="tool_result")
                        dbTools.complete_tool_call(tool_db_id, tool_result)

                        if tool_name == "close_review":
                            logger.info("LLM requested to close the review at iteration %d", loops_count)

                            output_data = json.loads(tool_result)
                            output_review_summary = output_data

                            finished = True
                    except Exception as e:
                        error_message = f"Error executing tool {tool_name} in review: {str(e)}"
                        llm.add_message("review", error_message, role="tool_result")
                        dbTools.complete_tool_call(tool_db_id, error_message, False)
                        logger.error("Tool %s failed in review: %s", tool_name, e)
            
        llm.close_chats()
        if finished:
            dbTools.end_run(review_id)
        else:
            dbTools.end_run(review_id, status="cancelled")

        return output_review_summary
    except Exception as e:
        logger.error("An error occurred during the review LLM call: %s. Closing chat and ending review run.", e, exc_info=True)
        llm.close_chats()
        dbTools.end_run(review_id, status="failed")
        return None

async def get_snapshot_ib() -> Dict[str, Any]:
    positions = await get_positions({})
    cash_balance = await get_cash_balance({})
    open_trades = await get_open_trades({})
    market_status = await get_date_hour_utc_and_markets({})

    return {
        "positions": positions["positions"],
        "cash_balances": cash_balance["cash_balances"],
        "open_trades": open_trades["open_trades"],
        "date_and_hour": market_status["date_and_hour"],
        "markets_status": market_status["markets"],
    }