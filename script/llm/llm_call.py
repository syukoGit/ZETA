from typing import Any, Dict, Tuple
from config import config
from db.db_tools import DBTools
from llm.prompt import get_prompt
from llm.tools.history.get_runs_to_review import get_runs_to_review
from llm.tools.ibkr.get_quote import get_quote
from llm.tools.utils.get_date_hour_utc_and_markets import get_date_hour_utc_and_markets
from logger import GREEN, RESET, get_logger, dynamic_log, dynamic_log_end
from llm.llm_provider import LLMFactory
from llm.tools.ibkr.get_cash_balance import get_cash_balance
from llm.tools.ibkr.get_open_trades import get_open_trades
from llm.tools.ibkr.get_positions import get_positions
from phase_resolver import get_current_phase
from utils.json_utils import dumps_json

logger = get_logger(__name__)

_dynamic_run_message = (
    f"{GREEN}[Current run] {RESET} Loop %s | Tool calls: %s (failed: %s)"
)
_dynamic_review_message = (
    f"{GREEN}[Review] {RESET} Loop %s | Tool calls: %s (failed: %s)"
)


async def run_llm_call(
    dbTools: DBTools,
    previous_reporting: str | None,
    last_review: str | None,
    max_loops: int = 20,
) -> Tuple[Dict, float]:
    llm = LLMFactory.get_provider(config().llm)
    logger.info("Using LLM provider: %s with model %s", llm.name, llm.model)

    run_id = None

    try:
        run_id = dbTools.start_run("llm_call", llm.name, llm.model)

        # Add initial system prompt to set the context for the LLM
        run_prompt = get_prompt(get_current_phase().config.prompt_file)
        if not run_prompt:
            logger.error("No prompt found for the current phase")

            llm.close_chats()
            dbTools.end_run(run_id, status="failed")

            return None, None

        llm.add_message("run", run_prompt, role="system")
        dbTools.add_message(run_id, "system", run_prompt)

        # Provide explicit phase routing context when multiple phases share the same prompt file.
        current_phase_message = f"CURRENT_PHASE: {get_current_phase().phase.value}"
        llm.add_message("run", current_phase_message, role="system")
        dbTools.add_message(run_id, "system", current_phase_message)

        # Add last reporting summary to the system prompt for context, if available
        summary_message = (
            "PREVIOUS_SUMMARY: " + dumps_json(previous_reporting)
            if previous_reporting
            else "No summary provided."
        )
        llm.add_message("run", summary_message, role="system")
        dbTools.add_message(run_id, "system", summary_message)

        # Add IB snapshot to the system prompt for context
        snapshot_ib = await get_snapshot_ib()
        snapshot_message = "SNAPSHOT_IB: " + dumps_json(snapshot_ib)
        llm.add_message("run", snapshot_message, role="system")
        dbTools.add_message(run_id, "system", snapshot_message)
        logger.debug("IB snapshot: %s", snapshot_ib)

        # Add last review summary to the system prompt for context, if available
        review_summary_message = (
            "LAST_REVIEW: " + dumps_json(last_review)
            if last_review
            else "No last review summary provided."
        )
        llm.add_message("run", review_summary_message, role="system")
        dbTools.add_message(run_id, "system", review_summary_message)
        logger.debug("Last review summary: %s", review_summary_message)

        loops_count = 0
        finished = False
        total_tool_calls = 0
        failed_tool_calls = 0

        output_summary = None
        output_time_before_next_run_s = None

        while not finished and loops_count < max_loops:
            loops_count += 1
            dynamic_log(
                _dynamic_run_message,
                f"{loops_count}/{max_loops}",
                total_tool_calls,
                failed_tool_calls,
            )
            (response, tool_calls) = llm.get_response("run")

            response_content = dumps_json(getattr(response, "content", response))

            llm.add_message("run", response_content, role="assistant")
            message_id = dbTools.add_message(run_id, "assistant", response)

            logger.debug("Tool calls received: %d", len(tool_calls))

            for tc in tool_calls:
                (tool_name, payload) = llm.get_tool_calls_info(tc)
                tool_db_id = dbTools.log_tool_call(message_id, tool_name, payload)

                if llm.is_client_side_tool(tc):
                    try:
                        tool_result = await llm.execute_client_side_tool(tc, message_id)
                        logger.debug("Tool %s result: %s", tool_name, tool_result)

                        llm.add_message(
                            "run", dumps_json(tool_result), role="tool_result"
                        )
                        dbTools.complete_tool_call(tool_db_id, tool_result)
                        total_tool_calls += 1
                        dynamic_log(
                            _dynamic_run_message,
                            f"{loops_count}/{max_loops}",
                            total_tool_calls,
                            failed_tool_calls,
                        )

                        if tool_name == "close_run":
                            logger.info(
                                "LLM requested to close the run at iteration %d",
                                loops_count,
                            )

                            output_summary = tool_result["summary"]
                            output_time_before_next_run_s = tool_result[
                                "time_before_next_run_s"
                            ]

                            finished = True
                    except Exception as e:
                        error_message = f"Error executing tool {tool_name}: {str(e)}"
                        llm.add_message("run", error_message, role="tool_result")
                        dbTools.complete_tool_call(
                            tool_db_id, {"error": error_message}, False
                        )
                        failed_tool_calls += 1
                        logger.error("Tool %s failed: %s", tool_name, e)
                else:
                    logger.debug(
                        "Server-side tool call received: %s with payload: %s",
                        tool_name,
                        payload,
                    )
                    dbTools.complete_tool_call(tool_db_id, None)
                    total_tool_calls += 1
                    dynamic_log(
                        _dynamic_run_message,
                        f"{loops_count}/{max_loops}",
                        total_tool_calls,
                        failed_tool_calls,
                    )

        dynamic_log_end()
        logger.info(
            "Run finished: %d loops, %d tool calls total (failed: %d)",
            loops_count,
            total_tool_calls,
            failed_tool_calls,
        )
        llm.close_chats()
        if finished:
            dbTools.end_run(run_id)
        else:
            dbTools.end_run(run_id, status="cancelled")

        return output_summary, output_time_before_next_run_s
    except Exception as e:
        dynamic_log_end()
        logger.error(
            "An error occurred during the LLM call: %s. Closing chat and ending run.",
            e,
            exc_info=True,
        )
        llm.close_chats()
        dbTools.end_run(run_id, status="failed")
        return None, None


async def run_llm_review_call(
    dbTools: DBTools, previous_review: str | None, max_loops: int = 20
) -> Dict:
    llm = LLMFactory.get_provider(config().review.llm)
    logger.info("Using LLM provider for review: %s with model %s", llm.name, llm.model)

    review_id = None

    try:
        review_id = dbTools.start_run("review", llm.name, llm.model)

        # Add initial system prompt to set the context for the LLM
        review_prompt = get_prompt("review_prompt.txt")
        if not review_prompt:
            logger.error("No review prompt found")

            llm.close_chats()
            dbTools.end_run(review_id, status="failed")

            return None

        llm.add_message("review", review_prompt, role="system")
        dbTools.add_message(review_id, "system", review_prompt)

        # Add last review summary to the system prompt for context, if available
        summary_message = (
            "PREVIOUS_REVIEW: " + dumps_json(previous_review)
            if previous_review
            else "No previous review summary provided."
        )
        llm.add_message("review", summary_message, role="system")
        dbTools.add_message(review_id, "system", summary_message)

        # Add IB snapshot to the system prompt for context
        snapshot_ib = await get_snapshot_ib()
        snapshot_message = "SNAPSHOT_IB: " + dumps_json(snapshot_ib)
        llm.add_message("review", snapshot_message, role="system")
        dbTools.add_message(review_id, "system", snapshot_message)
        logger.debug("IB snapshot for review: %s", snapshot_ib)

        # Add all runs since last review to the system prompt for context
        runs_to_review = await get_runs_to_review({})
        runs_message = "RUNS_TO_REVIEW: " + dumps_json(runs_to_review)
        llm.add_message("review", runs_message, role="system")
        dbTools.add_message(review_id, "system", runs_message)
        logger.debug("Runs to review: %s", runs_message)

        loops_count = 0
        finished = False
        total_tool_calls = 0
        failed_tool_calls = 0

        output_review_summary = None

        while not finished and loops_count < max_loops:
            loops_count += 1
            dynamic_log(
                _dynamic_review_message,
                f"{loops_count}/{max_loops}",
                total_tool_calls,
                failed_tool_calls,
            )
            (response, tool_calls) = llm.get_response("review")

            response_content = dumps_json(getattr(response, "content", response))

            llm.add_message("review", response_content, role="assistant")
            message_id = dbTools.add_message(review_id, "assistant", response)

            logger.debug("Tool calls received in review: %d", len(tool_calls))

            for tc in tool_calls:
                (tool_name, payload) = llm.get_tool_calls_info(tc)
                tool_db_id = dbTools.log_tool_call(message_id, tool_name, payload)

                if llm.is_client_side_tool(tc):
                    try:
                        tool_result = await llm.execute_client_side_tool(tc, message_id)
                        logger.debug(
                            "Tool %s result in review: %s", tool_name, tool_result
                        )

                        llm.add_message(
                            "review", dumps_json(tool_result), role="tool_result"
                        )
                        dbTools.complete_tool_call(tool_db_id, tool_result)
                        total_tool_calls += 1
                        dynamic_log(
                            _dynamic_review_message,
                            f"{loops_count}/{max_loops}",
                            total_tool_calls,
                            failed_tool_calls,
                        )

                        if tool_name == "close_review":
                            logger.info(
                                "LLM requested to close the review at iteration %d",
                                loops_count,
                            )

                            output_review_summary = tool_result

                            finished = True
                    except Exception as e:
                        error_message = (
                            f"Error executing tool {tool_name} in review: {str(e)}"
                        )
                        llm.add_message("review", error_message, role="tool_result")
                        dbTools.complete_tool_call(
                            tool_db_id, {"error": error_message}, False
                        )
                        logger.error("Tool %s failed in review: %s", tool_name, e)
                        failed_tool_calls += 1
                else:
                    logger.debug(
                        "Server-side tool call received in review: %s with payload: %s",
                        tool_name,
                        payload,
                    )
                    dbTools.complete_tool_call(tool_db_id, None)
                    total_tool_calls += 1
                    dynamic_log(
                        _dynamic_review_message,
                        f"{loops_count}/{max_loops}",
                        total_tool_calls,
                        failed_tool_calls,
                    )

        dynamic_log_end()
        logger.info(
            "Review finished: %d loops, %d tool calls total (failed: %d)",
            loops_count,
            total_tool_calls,
            failed_tool_calls,
        )
        llm.close_chats()
        if finished:
            dbTools.end_run(review_id)
        else:
            dbTools.end_run(review_id, status="cancelled")

        return output_review_summary
    except Exception as e:
        dynamic_log_end()
        logger.error(
            "An error occurred during the review LLM call: %s. Closing chat and ending review run.",
            e,
            exc_info=True,
        )
        llm.close_chats()
        dbTools.end_run(review_id, status="failed")
        return None


async def get_snapshot_ib() -> Dict[str, Any]:
    positions = await get_positions({})
    cash_balance = await get_cash_balance({})
    open_trades = await get_open_trades({})
    market_status = await get_date_hour_utc_and_markets({})

    quotes: Dict[str, Any] = {}
    for idx in config().snapshot.indices:
        try:
            result = await get_quote(
                {
                    "symbol": idx.symbol,
                    "exchange": idx.exchange,
                    "currency": idx.currency,
                }
            )
            if isinstance(result, dict):
                quotes[idx.symbol] = result.get("last")
            else:
                logger.error(
                    "get_quote for index %s returned non-dict result: %r",
                    idx.symbol,
                    result,
                )
                quotes[idx.symbol] = None
        except Exception as e:
            logger.error("Failed to fetch quote for index %s: %s", idx.symbol, e)
            quotes[idx.symbol] = None

    return {
        "positions": positions["positions"],
        "cash_balances": cash_balance["cash_balances"],
        "open_trades": open_trades["open_trades"],
        "date_and_hour": market_status["date_and_hour"],
        "markets_status": market_status["markets"],
        "quotes": quotes,
    }
