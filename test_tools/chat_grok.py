"""
Interactive Grok chat with tool-call confirmation.

Lets you chat with Grok while having access to all registered ZETA tools
(IBKR, memory, utils…). When Grok requests tool calls, they are displayed
and you decide whether to execute them.

Usage:
    python test_tools/chat_grok.py
"""

import asyncio
import json
import os
import sys

# Ensure the project root and script/ are on sys.path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "script"))

from utils.json_utils import dumps_json

from dotenv import load_dotenv

load_dotenv(os.path.join(_root, ".env"))

# ── Colour helpers ───────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}{msg}{RESET}")


def _fail(msg: str) -> None:
    print(f"  {RED}{msg}{RESET}")


def _info(msg: str) -> None:
    print(f"  {CYAN}{msg}{RESET}")


def _header(title: str) -> None:
    print(f"\n{BOLD}{YELLOW}{'═' * 50}")
    print(f"  {title}")
    print(f"{'═' * 50}{RESET}")


# ── Tool-call display & confirmation ─────────────────────────────────────
def _display_tool_call(index: int, name: str, args: dict) -> None:
    """Pretty-print a single tool call for user review."""
    print(f"\n  {YELLOW}┌─ Tool call #{index}: {BOLD}{name}{RESET}")
    if args:
        for k, v in args.items():
            val_str = dumps_json(v) if not isinstance(v, str) else v
            print(f"  {YELLOW}│  {CYAN}{k}{RESET}: {val_str}")
    else:
        print(f"  {YELLOW}│  {DIM}(no arguments){RESET}")
    print(f"  {YELLOW}└──────────────────────────────{RESET}")


def _ask_confirmation(tool_calls_info: list[tuple[str, dict]]) -> list[bool]:
    """Ask user which tool calls to execute. Returns a list of booleans."""
    n = len(tool_calls_info)
    if n == 0:
        return []

    print(f"\n{BOLD}{YELLOW}Grok wants to execute {n} tool call(s):{RESET}")
    for i, (name, args) in enumerate(tool_calls_info):
        _display_tool_call(i, name, args)

    while True:
        choice = input(
            f"\n{BOLD}Execute? [a]ll / [n]one / comma-separated indices (e.g. 0,2) / [q]uit chat: {RESET}"
        ).strip().lower()
        if choice in ("a", "all", "y", "yes", ""):
            return [True] * n
        if choice in ("n", "none", "no"):
            return [False] * n
        if choice in ("q", "quit"):
            raise KeyboardInterrupt
        # Try parsing indices
        try:
            indices = {int(x.strip()) for x in choice.split(",")}
            if all(0 <= idx < n for idx in indices):
                return [i in indices for i in range(n)]
            print(f"  {RED}Indices must be between 0 and {n - 1}.{RESET}")
        except ValueError:
            print(f"  {RED}Invalid input, try again.{RESET}")


# ── Main chat loop ──────────────────────────────────────────────────────
async def _chat_with_grok() -> None:
    """Interactive chat loop with Grok, including tool-call confirmation."""
    _header("Interactive Grok Chat")

    from config import get as config_get
    from db.database import init_db
    from db.db_tools import DBTools
    from ibkr.ibTools import init_ib_connection
    from llm.tools.base import get_tools

    llm_cfg = config_get("llm", {})
    model = llm_cfg.get("model")
    api_key = os.getenv("LLM_API_KEY")

    if not api_key:
        _fail("LLM_API_KEY environment variable is not set.")
        return
    if not model:
        _fail("No model configured in config.json → llm.model")
        return

    # ── Initialize DB ──
    _info("Initializing database...")
    try:
        db = init_db()
        db.create_tables()
        DBTools()
        _ok("Database ready.")
    except Exception as exc:
        _fail(f"Database init failed: {exc}")
        return

    # ── Initialize IBKR ──
    dry_run = config_get("dry_run", True)
    _info(f"Connecting to IBKR (dry_run={dry_run})...")
    try:
        await init_ib_connection(dry_run)
        _ok("IBKR connected.")
    except Exception as exc:
        _fail(f"IBKR connection failed: {exc}")
        _info("Continuing without IBKR — IBKR tools will fail if called.")

    _info(f"Model: {model}")

    from xai_sdk import Client
    from xai_sdk.chat import user, tool_result
    from xai_sdk.tools import web_search, x_search, get_tool_call_type
    from xai_sdk.chat import tool as xai_tool

    client = Client(api_key=api_key)

    # Build tool list (same as grok_provider)
    available_tools = get_tools()
    grok_tools = [
        x_search(enable_image_understanding=True, enable_video_understanding=True),
        web_search(enable_image_understanding=True),
        *[
            xai_tool(
                name=k,
                description=v.description,
                parameters=v.args_model.model_json_schema(),
            )
            for k, v in available_tools.items()
        ],
    ]

    _info(f"Tools loaded: {len(available_tools)} custom + web_search + x_search")
    _info("Available custom tools:")
    for name, spec in available_tools.items():
        print(f"    {DIM}• {name}{RESET}")

    print(f"\n  {CYAN}Type your message and press Enter. Type 'quit' or 'exit' to stop.{RESET}")

    chat = client.chat.create(model=model, tools=grok_tools, store_messages=True)
    previous_response_id = None

    while True:
        # ── User input ──
        try:
            user_input = input(f"\n{BOLD}{GREEN}You> {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input or user_input.lower() in ("quit", "exit"):
            break

        # (Re)create chat for multi-turn
        if previous_response_id is not None:
            chat = client.chat.create(
                model=model,
                tools=grok_tools,
                store_messages=True,
                previous_response_id=previous_response_id,
            )

        chat.append(user(user_input))

        # ── LLM loop (may iterate when tool calls are executed) ──
        max_tool_rounds = 20
        for _round in range(max_tool_rounds):
            # Stream response
            tool_calls = []
            response = None
            try:
                for response, chunk in chat.stream():
                    if chunk.tool_calls:
                        tool_calls.extend(chunk.tool_calls)
            except Exception as exc:
                _fail(f"Error during streaming: {exc}")
                break

            response_text = response.content if response and response.content else ""
            previous_response_id = response.id if response else previous_response_id

            if response_text:
                print(f"\n{BOLD}{CYAN}Grok>{RESET} {response_text}")

            if not tool_calls:
                break

            # ── Classify tool calls ──
            from xai_sdk.proto.v6.chat_pb2 import ToolCall as ToolCallPB

            client_side_calls = []
            server_side_calls = []
            for tc in tool_calls:
                if isinstance(tc, ToolCallPB) and get_tool_call_type(tc) == "client_side_tool":
                    name = tc.function.name
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    client_side_calls.append((name, args, tc))
                else:
                    server_side_calls.append(tc)

            if server_side_calls:
                _info(f"{len(server_side_calls)} server-side tool call(s) handled by Grok automatically.")

            if not client_side_calls:
                break

            # ── Ask user confirmation ──
            info_list = [(name, args) for name, args, _tc in client_side_calls]
            try:
                decisions = _ask_confirmation(info_list)
            except KeyboardInterrupt:
                print(f"\n{YELLOW}Chat interrupted.{RESET}")
                return

            # ── Execute approved tool calls ──
            results = []
            for (name, args, _tc), approved in zip(client_side_calls, decisions):
                if approved:
                    _info(f"Executing {name}...")
                    try:
                        tool_spec = available_tools[name]
                        validated = tool_spec.args_model(**args).model_dump()
                        result = await tool_spec.handler(validated)
                        result_json = dumps_json(result)
                        results.append(result_json)
                        truncated = result_json[:300] + ("…" if len(result_json) > 300 else "")
                        _ok(f"{name} → {truncated}")
                    except Exception as exc:
                        error_msg = f"Error executing {name}: {exc}"
                        results.append(error_msg)
                        _fail(error_msg)
                else:
                    skip_msg = f"Tool {name} was skipped by user."
                    results.append(skip_msg)
                    _info(skip_msg)

            if not results:
                break

            # Feed results back to Grok for the next round
            chat = client.chat.create(
                model=model,
                tools=grok_tools,
                store_messages=True,
                previous_response_id=previous_response_id,
            )
            for r in results:
                chat.append(tool_result(r))
        else:
            _info(f"Reached max tool rounds ({max_tool_rounds}), stopping.")

    print(f"\n{BOLD}{YELLOW}Chat ended.{RESET}")


def main() -> None:
    asyncio.run(_chat_with_grok())


if __name__ == "__main__":
    main()
