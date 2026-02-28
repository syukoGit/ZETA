import json
from typing import Dict, Tuple
from uuid import UUID
from config import get
from db.db_tools import DBTools
from llm.performance_review_prompt import PERFORMANCE_REVIEW_PROMPT
from llm.tools.history.get_runs_to_review import get_runs_to_review
from llm.tools.utils.get_date_hour_utc_and_markets import get_date_hour_utc_and_markets
from logger import get_logger
from llm.llm_provider import LLM, LLMFactory
from llm.start_prompt import DEFAULT_START_PROMPT
from llm.tools.ibkr.get_cash_balance import get_cash_balance
from llm.tools.ibkr.get_open_trades import get_open_trades
from llm.tools.ibkr.get_positions import get_positions
from utils.json_utils import ExtendedEncoder

logger = get_logger(__name__)


async def run_llm_call(dbTools: DBTools, previous_reporting: str | None, last_review: str | None, max_loops: int = 20) -> Tuple[Dict, float]:
    llm = LLMFactory.get_provider(get("llm"))
    logger.info("Using LLM provider: %s with model %s", llm.name, llm.model)

    run_id = None

    try:
        llm.new_chat(mode="run")
        run_id = dbTools.start_run("llm_call", llm.name, llm.model)

        # Add initial system prompt to set the context for the LLM
        llm.add_message(DEFAULT_START_PROMPT, role="system")
        dbTools.add_message(run_id, "system", DEFAULT_START_PROMPT)

        # Add last reporting summary to the system prompt for context, if available
        summary_message = "PREVIOUS_SUMMARY: " + json.dumps(previous_reporting, cls=ExtendedEncoder) if previous_reporting else "No summary provided."
        llm.add_message(summary_message, role="system")
        dbTools.add_message(run_id, "system", summary_message)

        # Add IB snapshot to the system prompt for context
        snapshot_ib = await get_snapshot_ib()
        snapshot_message = "SNAPSHOT_IB: " + json.dumps(snapshot_ib, cls=ExtendedEncoder)
        llm.add_message(snapshot_message, role="system")
        dbTools.add_message(run_id, "system", snapshot_message)
        logger.debug("IB snapshot: %s", snapshot_ib)

        # Add last performance review summary to the system prompt for context, if available
        review_summary_message = "LAST_REVIEW: " + json.dumps(last_review, cls=ExtendedEncoder) if last_review else "No last performance review summary provided."
        llm.add_message(review_summary_message, role="system")
        dbTools.add_message(run_id, "system", review_summary_message)
        logger.debug("Last performance review summary: %s", review_summary_message)

        response = ""
        loops_count = 0

        while loops_count < max_loops:
            loops_count += 1

            (response, tool_calls, response_id) = llm.get_response()

            if not response and not tool_calls:
                message = "No response and no tool calls. Send tool_calls or response to continue the run. If you want to end the run, call the close_run tool with the appropriate response and time_before_next_run."
                llm.add_message(message, role="system")
                dbTools.add_message(run_id, "system", message)
                logger.debug("No response and no tool calls, ending loop at iteration %d", loops_count)
                continue

            llm.add_message(response, role="assistant")
            message_id = dbTools.add_message(run_id, "assistant", response)

            if not tool_calls:
                logger.debug("No tool calls. Continuing loop at iteration %d", loops_count)
                llm.add_message("No tool calls received. If you want to end the run, call the close_run tool with the appropriate response and time_before_next_run.", role="system")
                llm.new_chat(mode="run", previous_response_id=response_id)
                continue

            # Check if llm calls close_run tool to end the loop early
            close_run_called = None
            for tc in tool_calls:
                if llm.is_client_side_tool(tc) and llm.get_tool_calls_info(tc)[0] == "close_run":
                    close_run_called = tc
                    break

            if close_run_called:
                try:
                    (close_run_tool_name, close_run_payload) = llm.get_tool_calls_info(close_run_called)
                    tool_db_id = dbTools.log_tool_call(message_id, close_run_tool_name, close_run_payload)

                    tool_result = await llm.execute_client_side_tool(close_run_called, message_id)

                    tool_result_data = json.loads(tool_result)
                    response = tool_result_data["summary"]
                    time_before_next_run_s = tool_result_data["time_before_next_run_s"]

                    dbTools.complete_tool_call(tool_db_id, tool_result)

                    llm.close_chat()
                    dbTools.end_run(run_id)
                    logger.info("LLM closes the run at iteration %d", loops_count)

                    return response, time_before_next_run_s
                except Exception as e:
                    error_message = f"Error executing tool close_run: {str(e)}"
                    logger.error("Error processing close_run tool call: %s", e)
                    llm.add_message(error_message, role="tool_result")
                    dbTools.complete_tool_call(tool_db_id, error_message, False)

                    continue

            logger.debug("Tool calls received: %d", len(tool_calls))

            # Collect client-side tool results before creating a new chat
            client_side_results = await execute_client_side_tools(llm, tool_calls, message_id, dbTools)

            llm.new_chat(mode="run", previous_response_id=response_id)
            
            # Only continue the loop if there are client-side tool results to send back
            if not client_side_results:
                logger.debug("All tool calls were server-side, ending loop at iteration %d", loops_count)
                continue

            for result in client_side_results:
                llm.add_message(result, role="tool_result")
        
        llm.close_chat()
        dbTools.end_run(run_id, status="cancelled")

        return None
    except Exception as e:
        logger.error("An error occurred during the LLM call: %s. Closing chat and ending run.", e, exc_info=True)
        llm.close_chat()
        dbTools.end_run(run_id, status="failed")
        return None

async def run_llm_review_call(dbTools: DBTools, previous_review: str | None, max_loops: int = 20) -> Dict:
    llm = LLMFactory.get_provider(get("performance_review").get("llm"))
    logger.info("Using LLM provider for performance review: %s with model %s", llm.name, llm.model)

    review_id = None

    try:
        llm.new_chat(mode="performance_review")
        review_id = dbTools.start_run("performance_review", llm.name, llm.model)

        # Add initial system prompt to set the context for the LLM
        llm.add_message(PERFORMANCE_REVIEW_PROMPT, role="system")
        dbTools.add_message(review_id, "system", PERFORMANCE_REVIEW_PROMPT)

        # Add last review summary to the system prompt for context, if available
        summary_message = "PREVIOUS_REVIEW: " + json.dumps(previous_review, cls=ExtendedEncoder) if previous_review else "No previous review summary provided."
        llm.add_message(summary_message, role="system")
        dbTools.add_message(review_id, "system", summary_message)

        # Add IB snapshot to the system prompt for context
        snapshot_ib = await get_snapshot_ib()
        snapshot_message = "SNAPSHOT_IB: " + json.dumps(snapshot_ib, cls=ExtendedEncoder)
        llm.add_message(snapshot_message, role="system")
        dbTools.add_message(review_id, "system", snapshot_message)
        logger.debug("IB snapshot for review: %s", snapshot_ib)

        # Add all runs since last review to the system prompt for context
        runs_to_review = await get_runs_to_review({})
        runs_message = "RUNS_TO_REVIEW: " + json.dumps(runs_to_review, cls=ExtendedEncoder)
        llm.add_message(runs_message, role="system")
        dbTools.add_message(review_id, "system", runs_message)
        logger.debug("Runs to review: %s", runs_message)

        response = ""
        loops_count = 0

        while loops_count < max_loops:
            loops_count += 1

            (response, tool_calls, response_id) = llm.get_response()

            if not response and not tool_calls:
                message = "No response and no tool calls. Send tool_calls or response to continue the review. If you want to end the review, call the close_performance_review tool with the appropriate response."
                llm.add_message(message, role="system")
                dbTools.add_message(review_id, "system", message)
                logger.debug("No response and no tool calls, ending review loop at iteration %d", loops_count)
                continue

            llm.add_message(response, role="assistant")
            message_id = dbTools.add_message(review_id, "assistant", response)

            if not tool_calls:
                logger.debug("No tool calls. Continuing review loop at iteration %d", loops_count)
                llm.add_message("No tool calls received. If you want to end the review, call the close_performance_review tool with the appropriate response.", role="system")
                llm.new_chat(mode="performance_review", previous_response_id=response_id)
                continue

            close_run_called = None
            for tc in tool_calls:
                if llm.is_client_side_tool(tc) and llm.get_tool_calls_info(tc)[0] == "close_performance_review":
                    close_run_called = tc
                    break
            
            if close_run_called:
                try:
                    (tool_name, payload) = llm.get_tool_calls_info(close_run_called)
                    tool_db_id = dbTools.log_tool_call(message_id, tool_name, payload)

                    tool_result = await llm.execute_client_side_tool(close_run_called, message_id)

                    review_summary = json.loads(tool_result)
                    
                    dbTools.complete_tool_call(tool_db_id, tool_result)

                    llm.close_chat()
                    dbTools.end_run(review_id)
                    logger.info("LLM closes the performance review at iteration %d", loops_count)

                    return review_summary
                except Exception as e:
                    error_message = f"Error executing tool close_performance_review: {str(e)}"
                    logger.error("Error processing close_performance_review tool call: %s", e)
                    llm.add_message(error_message, role="tool_result")
                    dbTools.complete_tool_call(tool_db_id, error_message, False)

                    continue
            
            logger.debug("Tool calls received in review: %d", len(tool_calls))

            client_side_results = await execute_client_side_tools(llm, tool_calls, message_id, dbTools)
            llm.new_chat(mode="performance_review", previous_response_id=response_id)

            if not client_side_results:
                logger.debug("All tool calls were server-side in review, ending loop at iteration %d", loops_count)
                continue

            for result in client_side_results:
                llm.add_message(result, role="tool_result")
        
        llm.close_chat()
        dbTools.end_run(review_id, status="cancelled")

        return None
    except Exception as e:
        logger.error("An error occurred during the performance review LLM call: %s. Closing chat and ending review run.", e, exc_info=True)
        llm.close_chat()
        dbTools.end_run(review_id, status="failed")
        return None

async def execute_client_side_tools(llm: LLM, tool_calls: list, message_id: UUID, dbTools: DBTools) -> list:
    client_side_results = []
    for tool_call in tool_calls:
        (tool_name, payload) = llm.get_tool_calls_info(tool_call)
        logger.debug("Executing tool: %s with payload: %s", tool_name, payload)
        tool_db_id = dbTools.log_tool_call(message_id, tool_name, payload)

        if llm.is_client_side_tool(tool_call):
            try:
                tool_result = await llm.execute_client_side_tool(tool_call, message_id)
                logger.debug("Tool %s result: %s", tool_name, tool_result[:200] if isinstance(tool_result, str) else tool_result)
                client_side_results.append(tool_result)
                dbTools.complete_tool_call(tool_db_id, tool_result)
            except Exception as e:
                error_message = f"Error executing tool {tool_name}: {str(e)}"
                logger.error("Tool %s failed: %s", tool_name, e)
                client_side_results.append(error_message)
                dbTools.complete_tool_call(tool_db_id, error_message, False)
        else:
            dbTools.complete_tool_call(tool_db_id, None)
    
    return client_side_results

async def get_snapshot_ib() -> str:
    positions = await get_positions({})
    cash_balance = await get_cash_balance({})
    open_trades = await get_open_trades({})
    market_status = await get_date_hour_utc_and_markets({})

    snapshot_ib = {
        "positions": positions["positions"],
        "cash_balances": cash_balance["cash_balances"],
        "open_trades": open_trades["open_trades"],
        "date_and_hour": market_status["date_and_hour"],
        "markets_status": market_status["markets"],
    }

    return json.dumps(snapshot_ib, cls=ExtendedEncoder)