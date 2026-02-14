import json
from db.db_tools import DBTools
from logger import get_logger
from llm.llm_provider import LLMFactory
from llm.start_prompt import DEFAULT_START_PROMPT
from llm.tools.ibkr.get_cash_balance import get_cash_balance
from llm.tools.ibkr.get_open_trades import get_open_trades
from llm.tools.ibkr.get_positions import get_positions

logger = get_logger(__name__)


async def run_llm_call(dbTools: DBTools, previous_reporting: str | None, max_loops: int = 20) -> str:
    llm = LLMFactory.get_provider()
    logger.info("Using LLM provider: %s with model %s", llm.name, llm.model)

    run_id = None

    try:
        llm.new_chat()
        run_id = dbTools.start_run("llm_call", llm.name, llm.model)

        llm.add_message(DEFAULT_START_PROMPT, role="system")
        dbTools.add_message(run_id, "system", DEFAULT_START_PROMPT)

        summary_message = "SUMMARY_PREV: " + json.dumps(previous_reporting) if previous_reporting else "No summary provided."
        llm.add_message(summary_message, role="system")
        dbTools.add_message(run_id, "system", summary_message)

        positions = await get_positions({})
        cash_balance = await get_cash_balance({})
        open_trades = await get_open_trades({})

        snapshot_ib = {
            "positions": positions["positions"],
            "cash_balances": cash_balance["cash_balances"],
            "open_trades": open_trades["open_trades"],
        }

        snapshot_message = "SNAPSHOT_IB: " + json.dumps(snapshot_ib)
        llm.add_message(snapshot_message, role="system")
        dbTools.add_message(run_id, "system", snapshot_message)
        logger.debug("IB snapshot: %s", json.dumps(snapshot_ib, default=str))

        response = ""
        loops_count = 0

        while loops_count < max_loops:
            (response, tool_calls, response_id) = llm.get_response()
            llm.add_message(response, role="assistant")
            message_id = dbTools.add_message(run_id, "assistant", response)

            if not tool_calls:
                logger.debug("No tool calls, ending loop at iteration %d", loops_count)
                break

            logger.debug("Tool calls received: %d", len(tool_calls))

            # Collect client-side tool results before creating a new chat
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

            # Only continue the loop if there are client-side tool results to send back
            if not client_side_results:
                logger.debug("All tool calls were server-side, ending loop at iteration %d", loops_count)
                break

            llm.new_chat(response_id)
            for result in client_side_results:
                llm.add_message(result, role="tool_result")

            loops_count += 1
        
        llm.close_chat()
        dbTools.end_run(run_id)

        return response
    except Exception as e:
        logger.error("An error occurred during the LLM call: %s. Closing chat and ending run.", e, exc_info=True)
        llm.close_chat()
        dbTools.end_run(run_id, status="failed")
        return None