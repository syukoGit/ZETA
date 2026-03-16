import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
from uuid import UUID

from config import config
from db.db_tools import DBTools
from llm.context_builder import build_context
from llm.prompt import get_prompt, render_template
from logger import GREEN, RESET, get_logger, dynamic_log, dynamic_log_end
from llm.llm_provider import LLM, LLMFactory, ChatMode
from phase_resolver import get_current_phase
from utils.json_utils import dumps_json

logger = get_logger(__name__)

_dynamic_run_message = (
    f"{GREEN}[Current run] {RESET} Loop %s | Tool calls: %s (failed: %s)"
)
_dynamic_review_message = (
    f"{GREEN}[Review] {RESET} Loop %s | Tool calls: %s (failed: %s)"
)


# Limit for concurrent client-side tool executions to avoid unbounded bursts
_MAX_CONCURRENT_CLIENT_TOOLS = 10


async def _execute_client_tool_with_limit(
    llm: LLM,
    tc: Any,
    message_id: UUID,
    semaphore: asyncio.Semaphore,
) -> Any:
    """
    Wrapper around llm.execute_client_side_tool that enforces a concurrency limit
    via an asyncio.Semaphore.
    """
    async with semaphore:
        return await llm.execute_client_side_tool(tc, message_id)


@dataclass
class ToolExecResult:
    """Result of a single tool execution (client-side or server-side)."""

    tool_name: str
    tool_db_id: UUID
    result: dict | None = None
    error: str | None = None
    is_server_side: bool = False


async def _process_tool_calls(
    llm: LLM,
    dbTools: DBTools,
    tool_calls: list,
    message_id: UUID,
    chat_mode: ChatMode,
) -> Tuple[List[ToolExecResult], int, int]:
    # 1. Pre-log every tool call and classify client-side vs server-side
    prepared: List[Tuple[Any, str, UUID, bool]] = []  # (tc, name, db_id, is_client)
    for tc in tool_calls:
        tool_name, payload = llm.get_tool_calls_info(tc)
        tool_db_id = dbTools.log_tool_call(message_id, tool_name, payload)
        is_client = llm.is_client_side_tool(tc)
        prepared.append((tc, tool_name, tool_db_id, is_client))

    # 2. Launch client-side tools concurrently, but with a bounded concurrency
    # Build a future for each slot; server-side slots get None.
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CLIENT_TOOLS)
    futures: List[asyncio.Task | None] = []
    for tc, tool_name, tool_db_id, is_client in prepared:
        if is_client:
            futures.append(
                asyncio.create_task(
                    _execute_client_tool_with_limit(
                        llm=llm,
                        tc=tc,
                        message_id=message_id,
                        semaphore=semaphore,
                    )
                )
            )
        else:
            futures.append(None)

    # Await only the client-side tasks (gather preserves order)
    client_tasks = [f for f in futures if f is not None]
    if client_tasks:
        await asyncio.gather(*client_tasks, return_exceptions=True)

    # 3. Post-process results sequentially in original order
    results: List[ToolExecResult] = []
    success_count = 0
    fail_count = 0

    for idx, (tc, tool_name, tool_db_id, is_client) in enumerate(prepared):
        if not is_client:
            # Server-side tool: nothing to execute, just log completion
            logger.debug(
                "Server-side tool call received: %s",
                tool_name,
            )
            dbTools.complete_tool_call(tool_db_id, None)
            success_count += 1
            results.append(
                ToolExecResult(
                    tool_name=tool_name,
                    tool_db_id=tool_db_id,
                    is_server_side=True,
                )
            )
            continue

        # Client-side tool: retrieve result from the completed future
        future = futures[idx]
        exec_result = ToolExecResult(tool_name=tool_name, tool_db_id=tool_db_id)

        assert future is not None
        try:
            # If the task was cancelled, this will raise asyncio.CancelledError
            if future.cancelled():
                raise asyncio.CancelledError()
            exc = future.exception()
        except asyncio.CancelledError as cancel_exc:
            error_message = f"Tool {tool_name} was cancelled: {str(cancel_exc)}"
            llm.add_message(chat_mode, error_message, role="tool_result")
            dbTools.complete_tool_call(tool_db_id, {"error": error_message}, False)
            exec_result.error = error_message
            fail_count += 1
            logger.warning("Tool %s was cancelled: %s", tool_name, cancel_exc)
        else:
            if exc is not None:
                error_message = f"Error executing tool {tool_name}: {str(exc)}"
                llm.add_message(chat_mode, error_message, role="tool_result")
                dbTools.complete_tool_call(tool_db_id, {"error": error_message}, False)
                exec_result.error = error_message
                fail_count += 1
                logger.error("Tool %s failed: %s", tool_name, exc)
            else:
                tool_result = future.result()
                logger.debug("Tool %s result: %s", tool_name, tool_result)
                llm.add_message(chat_mode, dumps_json(tool_result), role="tool_result")
                dbTools.complete_tool_call(tool_db_id, tool_result)
                exec_result.result = tool_result
                success_count += 1

        results.append(exec_result)

    return results, success_count, fail_count


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

        # Build and render the dynamic context user message from template
        context_template = get_prompt("context.txt")
        if context_template:
            static_vars: dict[str, str] = {
                "previous_summary": (
                    dumps_json(previous_reporting) if previous_reporting else "None"
                ),
                "last_review": dumps_json(last_review) if last_review else "None",
            }
            context_vars = await build_context(context_template, static_vars)
            context_message = render_template(context_template, context_vars)
            llm.add_message("run", context_message, role="user")
            dbTools.add_message(run_id, "user", context_message)
        else:
            logger.warning("No context template found (context.txt)")

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

            results, ok, fail = await _process_tool_calls(
                llm, dbTools, tool_calls, message_id, "run"
            )
            total_tool_calls += ok
            failed_tool_calls += fail
            dynamic_log(
                _dynamic_run_message,
                f"{loops_count}/{max_loops}",
                total_tool_calls,
                failed_tool_calls,
            )

            for r in results:
                if r.tool_name == "close_run" and r.result is not None:
                    logger.info(
                        "LLM requested to close the run at iteration %d",
                        loops_count,
                    )
                    output_summary = r.result["summary"]
                    output_time_before_next_run_s = r.result["time_before_next_run_s"]
                    finished = True

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

        # Build and render the dynamic context user message from template
        review_context_template = get_prompt("review_context.txt")
        if review_context_template:
            static_vars: dict[str, str] = {
                "previous_review": (
                    dumps_json(previous_review) if previous_review else "None"
                ),
            }
            review_context_vars = await build_context(
                review_context_template, static_vars
            )
            review_context_message = render_template(
                review_context_template, review_context_vars
            )
            llm.add_message("review", review_context_message, role="user")
            dbTools.add_message(review_id, "user", review_context_message)
        else:
            logger.warning("No review context template found (review_context.txt)")

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

            results, ok, fail = await _process_tool_calls(
                llm, dbTools, tool_calls, message_id, "review"
            )
            total_tool_calls += ok
            failed_tool_calls += fail
            dynamic_log(
                _dynamic_review_message,
                f"{loops_count}/{max_loops}",
                total_tool_calls,
                failed_tool_calls,
            )

            for r in results:
                if r.tool_name == "close_review" and r.result is not None:
                    logger.info(
                        "LLM requested to close the review at iteration %d",
                        loops_count,
                    )
                    output_review_summary = r.result
                    finished = True

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
