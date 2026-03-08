from tools_utils.init import init

init()

import asyncio
import os

from config import config
from db.db_tools import DBTools
from llm.llm_provider import LLM, LLMFactory
from llm.tools.base import get_tools
from test_tools.tools_utils.check_connections import init_database, init_ibkr
from test_tools.tools_utils.display import *
from utils.json_utils import dumps_json


_ROLE_COLOR = {
    "user": YELLOW,
    "llm": CYAN,
    "tool_result": f"{DIM}{MAGENTA}",
}


def _display_message(sender: str, role: str, content: str) -> None:
    color = _ROLE_COLOR[role]
    message(f"\n{color}{BOLD}{sender} >{RESET} {content}")


def _display_tool_call(
    tc_name: str, args, is_client_side_tc: bool, label: str = ""
) -> None:
    color = MAGENTA if is_client_side_tc else BLUE
    tc_side_txt = "Client-side" if is_client_side_tc else "Server-side"
    label_prefix = f"{label} " if label else ""

    message(f"\n  {color}┌─ {label_prefix}Tool call ({tc_side_txt}) : {BOLD}{tc_name}")
    if args:
        for k, v in args.items():
            val_str = dumps_json(v) if not isinstance(v, str) else v
            message(f"  {color}│  {CYAN}{k}{RESET}: {val_str}")
    else:
        message(f"  {color}│  {DIM}(no arguments)")
    message(f"  {color}└──────────────────────────────")


def _parse_client_selection(selection: str, max_items: int):
    normalized = selection.strip().lower()
    if normalized == "all" or not normalized:
        return set(range(max_items)), None
    if normalized in {"none", "skip"}:
        return set(), None

    selected = set()
    parts = [p.strip() for p in selection.split(",") if p.strip()]
    if not parts:
        return None, "Selection is empty."

    for part in parts:
        if not part.isdigit():
            return None, f"Invalid index '{part}'."

        index = int(part)
        if index < 1 or index > max_items:
            return None, f"Index out of range: {index}."

        selected.add(index - 1)

    return selected, None


async def _main() -> None:
    header("Interactive LLM Chat")

    llm_cfg = config().llm
    provider = llm_cfg.provider
    model = llm_cfg.model
    api_key = os.getenv("LLM_API_KEY")

    if not api_key:
        fail("LLM_API_KEY environment variable is not set.")
        return
    if not provider:
        fail("LLM provider not specified in config.json → llm.provider")
        return
    if not model:
        fail("No model configured in config.json → llm.model")
        return

    # Initialize DB
    db_init = init_database("chat_with_llm")
    if db_init is None:
        fail("Database initialization failed.")
        return
    _, run_id, message_id = db_init

    # Initialize IBKR
    await init_ibkr()

    header("Configuration")
    info(f"Provider: {provider}")
    info(f"Model: {model}")

    llm = LLMFactory.get_provider(config().llm)

    try:
        available_tools = {
            name: spec
            for name, spec in get_tools().items()
            if name not in {"close_run", "close_review"}
        }

        info(
            f"Tools loaded: {len(available_tools)} client side tools + web_search + x_search"
        )
        info("Available client side tools:")
        for name, _ in available_tools.items():
            message(f"    {DIM}- {name}")

        info(f"\n  Type your message and press Enter. Type 'quit' or 'exit' to stop.")

        need_user_input = True
        while True:
            # User input
            if need_user_input:
                try:
                    user_input = prompt(f"\n{BOLD}{_ROLE_COLOR['user']}You> ")
                except (EOFError, KeyboardInterrupt):
                    break
                if user_input.lower() in ("quit", "exit"):
                    break

                if user_input:
                    llm.add_message("run", user_input, role="user")

            # Get LLM response and tool calls
            (response, tool_calls) = llm.get_response("run")

            # Process tool calls
            if tool_calls:
                tool_call_rows = []
                for tc in tool_calls:
                    is_client_side_tc = llm.is_client_side_tool(tc)
                    tc_name, args = llm.get_tool_calls_info(tc)
                    tool_call_rows.append(
                        {
                            "tc": tc,
                            "is_client": is_client_side_tc,
                            "tc_name": tc_name,
                            "args": args,
                        }
                    )

                server_calls = [row for row in tool_call_rows if not row["is_client"]]
                client_calls = [row for row in tool_call_rows if row["is_client"]]

                if server_calls:
                    for row in server_calls:
                        _display_tool_call(
                            row["tc_name"],
                            row["args"],
                            row["is_client"],
                        )

                for i, row in enumerate(client_calls, start=1):
                    _display_tool_call(
                        row["tc_name"],
                        row["args"],
                        row["is_client"],
                        label=f"[{i}]",
                    )

                if client_calls:
                    while True:
                        selection_input = prompt(
                            f"\n{BOLD}Execute client-side tool calls? [ALL/skip/indexes (1-{len(client_calls)})]: "
                        )
                        selected_indices, error = _parse_client_selection(
                            selection_input, len(client_calls)
                        )
                        if error:
                            fail(error)
                            continue
                        break

                    if not selected_indices:
                        info("No client-side tool call executed.")
                        continue

                    info(f"Executing {len(selected_indices)} client-side tool call(s)...")
                    for i, row in enumerate(client_calls):
                        if i not in selected_indices:
                            continue

                        result = await llm.execute_client_side_tool(row["tc"], message_id)
                        serialized_result = dumps_json(result)
                        llm.add_message("run", serialized_result, role="tool_result")
                        _display_message(
                            f"Tool Result {i + 1}", "tool_result", serialized_result
                        )

            # If LLM response has a text response, then display it
            raw_content = getattr(response, "content", response)
            if isinstance(raw_content, str):
                response_content = raw_content
            else:
                response_content = dumps_json(raw_content)

            if response_content.strip():
                llm.add_message("run", response_content, role="assistant")
                _display_message(provider, "llm", response_content)

            need_user_input = not tool_calls or not client_calls
    except Exception as exc:
        fail(f"An error occurred: {exc}")
    finally:
        db_tools = DBTools()
        if run_id is not None:
            db_tools.end_run(run_id)

    message(f"\n{BOLD}{YELLOW}Chat ended.")


if __name__ == "__main__":
    asyncio.run(_main())
