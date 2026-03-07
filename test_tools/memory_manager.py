from tools_utils.init import init

init()

import asyncio

from db.db_tools import DBTools
from llm.tools.base import get_tools
from test_tools.tools_utils.check_connections import init_database
from test_tools.tools_utils.display import *
from utils.json_utils import dumps_json


def _print_memory(mem: dict, index: int | None = None) -> None:
    """Pretty-print a single memory entry."""
    prefix = f"#{index} " if index is not None else ""
    mid = mem.get("memory_id") or mem.get("id", "?")
    title = mem.get("title", "")
    status = mem.get("status", "")
    mtype = mem.get("memory_type", "")
    similarity = mem.get("similarity")

    header_parts = [f"{prefix}{BOLD}{title}"]
    if mtype:
        header_parts.append(f"{DIM}[{mtype}]")
    if status:
        colour = (
            GREEN if status == "active" else YELLOW if status == "deprecated" else CYAN
        )
        header_parts.append(f"{colour}({status})")
    if similarity is not None:
        header_parts.append(f"{DIM}sim={similarity:.3f}")

    message(f"\n  {'  '.join(header_parts)}")
    message(f"  {DIM}ID: {mid}")

    content = mem.get("content", "")
    if content:
        # Show first 500 chars
        truncated = content[:500] + ("…" if len(content) > 500 else "")
        for line in truncated.splitlines():
            message(f"    {line}")

    tags = mem.get("tags")
    if tags:
        message(f"  {CYAN}Tags: {', '.join(tags)}")

    meta = mem.get("meta")
    if meta:
        message(f"  {DIM}Meta: {dumps_json(meta)}")


# Commands
async def cmd_search(tools: dict, message_id: str) -> None:
    query = prompt(f"  {CYAN}Search query: ")
    if not query:
        return

    limit_str = prompt(f"  {CYAN}Max results [{DIM}10{RESET}{CYAN}]: ")
    limit = int(limit_str) if limit_str.isdigit() else 10

    tags_str = prompt(
        f"  {CYAN}Filter by tags (comma-separated, leave empty for all): "
    )
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] or None

    types_str = prompt(
        f"  {CYAN}Filter by memory types (comma-separated, leave empty for all): "
    )
    memory_types = [t.strip() for t in types_str.split(",") if t.strip()] or None

    args = {
        "query": query,
        "limit": limit,
        "message_id": message_id,
        "min_similarity": 0,
    }
    if tags:
        args["tags"] = tags
    if memory_types:
        args["memory_types"] = memory_types

    info("Searching...")
    result = await tools["search_memory"].handler(args)

    if "error" in result:
        fail(f"Error: {result['error']}")
        return

    entries = result.get("results", [])
    if not entries:
        info("No results found.")
        return

    ok(f"{len(entries)} result(s) found:")
    for i, entry in enumerate(entries):
        _print_memory(entry, index=i)


async def cmd_create(tools: dict, message_id: str) -> None:
    """Create a new memory entry."""
    title = prompt(f"  {CYAN}Title: ")
    content = prompt(f"  {CYAN}Content: ")
    if not content:
        fail("Content is required.")
        return

    memory_type = prompt(f"  {CYAN}Type (e.g. thesis, note, observation): ") or None
    source = prompt(f"  {CYAN}Source (optional): ") or None
    tags_str = prompt(f"  {CYAN}Tags (comma-separated, optional): ") or None
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] or None

    args: dict = {"content": content, "message_id": message_id}
    if title:
        args["title"] = title
    if memory_type:
        args["memory_type"] = memory_type
    if source:
        args["source"] = source
    if tags:
        args["tags"] = tags

    info("Creating memory...")
    result = await tools["memory_create"].handler(args)

    if "error" in result:
        fail(f"Error: {result['error']}")
    else:
        ok(f"Memory created — ID: {result.get('memory_id')}")
        mem = result.get("memory")
        if mem:
            _print_memory(mem)


async def cmd_get(tools: dict, message_id: str) -> None:
    """Retrieve a memory by its ID."""
    mid = prompt(f"  {CYAN}Memory ID (UUID): ")
    if not mid:
        return

    info("Fetching...")
    result = await tools["memory_get_by_id"].handler(
        {"memory_id": mid, "message_id": message_id}
    )

    if "error" in result:
        fail(f"Error: {result['error']}")
    else:
        entry = result.get("entry", result)
        _print_memory(entry)


async def cmd_update(tools: dict, message_id: str) -> None:
    """Update an existing memory entry."""
    mid = prompt(f"  {CYAN}Memory ID (UUID): ")
    if not mid:
        return

    # Show current state first
    current = await tools["memory_get_by_id"].handler(
        {"memory_id": mid, "message_id": message_id}
    )
    if "error" in current:
        fail(f"Error: {current['error']}")
        return
    info("Current entry:")
    _print_memory(current.get("entry", current))

    reason = prompt(f"\n  {CYAN}Reason for update: ")
    if not reason:
        fail("A reason is required.")
        return

    new_content = prompt(f"  {CYAN}New content (leave empty to keep): ") or None
    tags_str = prompt(f"  {CYAN}New tags (comma-separated, leave empty to keep): ")
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] or None

    args: dict = {"memory_id": mid, "reason": reason, "message_id": message_id}
    if new_content:
        args["content"] = new_content
    if tags:
        args["tags"] = tags

    info("Updating...")
    result = await tools["memory_update"].handler(args)

    if "error" in result:
        fail(f"Error: {result['error']}")
    else:
        ok(f"Memory {mid} updated.")
        mem = result.get("memory")
        if mem:
            _print_memory(mem)


async def cmd_deprecate(tools: dict, message_id: str) -> None:
    """Deprecate a memory entry."""
    mid = prompt(f"  {CYAN}Memory ID (UUID): {RESET}")
    if not mid:
        return

    # Show current state first
    current = await tools["memory_get_by_id"].handler(
        {"memory_id": mid, "message_id": message_id}
    )
    if "error" in current:
        fail(f"Error: {current['error']}")
        return
    info("Entry to deprecate:")
    _print_memory(current.get("entry", current))

    confirm = prompt(f"\n  {YELLOW}Deprecate this entry? [y/N]: {RESET}")
    if confirm not in ("y", "yes"):
        info("Cancelled.")
        return

    reason = prompt(f"  {CYAN}Reason: {RESET}")
    if not reason:
        fail("A reason is required.")
        return

    info("Deprecating...")
    result = await tools["memory_deprecate"].handler(
        {"memory_id": mid, "reason": reason, "message_id": message_id}
    )

    if "error" in result:
        fail(f"Error: {result['error']}")
    else:
        ok(f"Memory {mid} deprecated.")


# Main loop
COMMANDS = {
    "search": ("Search memories by query", cmd_search),
    "create": ("Create a new memory", cmd_create),
    "get": ("Get a memory by ID", cmd_get),
    "update": ("Update an existing memory", cmd_update),
    "deprecate": ("Deprecate a memory", cmd_deprecate),
}

MEMORY_TOOL_NAMES = [
    "search_memory",
    "memory_create",
    "memory_get_by_id",
    "memory_update",
    "memory_deprecate",
]


async def _main() -> None:
    header("Memory Manager")

    _, run_id, message_id = init_database("memory_manager")

    try:
        all_tools = get_tools()
        memory_tools = {k: all_tools[k] for k in MEMORY_TOOL_NAMES if k in all_tools}

        missing = set(MEMORY_TOOL_NAMES) - set(memory_tools.keys())
        if missing:
            fail(f"Missing tools: {', '.join(missing)}")
            return

        ok(f"Memory tools loaded: {', '.join(memory_tools.keys())}")

        # Menu loop
        info(f"\n  Commands:")
        for cmd, (desc, _) in COMMANDS.items():
            message(f"    {BOLD}{cmd:<12}{RESET} {desc}")
        message(f"    {BOLD}{'quit':<12}{RESET} Exit")

        while True:
            try:
                choice = prompt(f"\n{BOLD}{GREEN}memory> ")
            except (EOFError, KeyboardInterrupt):
                break

            if choice in ("quit", "exit", "q"):
                break

            if choice in COMMANDS:
                _, handler = COMMANDS[choice]
                try:
                    await handler(memory_tools, message_id)
                except Exception as exc:
                    fail(f"Unexpected error: {exc}")
            elif choice == "":
                continue
            else:
                fail(f"Unknown command: {choice}")
                info(f"Available: {', '.join(COMMANDS.keys())}, quit")
    finally:
        db_tools = DBTools()
        if run_id is not None:
            db_tools.end_run(run_id)

    message(f"\n{BOLD}{YELLOW}Goodbye.")


if __name__ == "__main__":
    asyncio.run(_main())
