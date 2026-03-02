"""
Interactive memory manager — search, create, update, deprecate memories.

Uses the same registered tools as ZETA (search_memory, memory_create,
memory_update, memory_get_by_id, memory_deprecate).

Usage:
    python test_tools/memory_manager.py
"""

import asyncio
import os
import sys
from uuid import UUID

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


def _print_memory(mem: dict, index: int | None = None) -> None:
    """Pretty-print a single memory entry."""
    prefix = f"#{index} " if index is not None else ""
    mid = mem.get("memory_id") or mem.get("id", "?")
    title = mem.get("title", "")
    status = mem.get("status", "")
    mtype = mem.get("memory_type", "")
    similarity = mem.get("similarity")

    header_parts = [f"{prefix}{BOLD}{title}{RESET}"]
    if mtype:
        header_parts.append(f"{DIM}[{mtype}]{RESET}")
    if status:
        colour = GREEN if status == "active" else YELLOW if status == "deprecated" else CYAN
        header_parts.append(f"{colour}({status}){RESET}")
    if similarity is not None:
        header_parts.append(f"{DIM}sim={similarity:.3f}{RESET}")

    print(f"\n  {'  '.join(header_parts)}")
    print(f"  {DIM}ID: {mid}{RESET}")

    content = mem.get("content", "")
    if content:
        # Show first 500 chars
        truncated = content[:500] + ("…" if len(content) > 500 else "")
        for line in truncated.splitlines():
            print(f"    {line}")

    tags = mem.get("tags")
    if tags:
        print(f"  {CYAN}Tags: {', '.join(tags)}{RESET}")

    meta = mem.get("meta")
    if meta:
        print(f"  {DIM}Meta: {dumps_json(meta)}{RESET}")


# ── Commands ─────────────────────────────────────────────────────────────
async def cmd_search(tools: dict) -> None:
    """Search memory by semantic query."""
    query = input(f"  {CYAN}Search query: {RESET}").strip()
    if not query:
        return

    limit_str = input(f"  {CYAN}Max results [{DIM}10{RESET}{CYAN}]: {RESET}").strip()
    limit = int(limit_str) if limit_str.isdigit() else 10

    tags_str = input(f"  {CYAN}Filter by tags (comma-separated, leave empty for all): {RESET}").strip()
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] or None

    types_str = input(f"  {CYAN}Filter by memory types (comma-separated, leave empty for all): {RESET}").strip()
    memory_types = [t.strip() for t in types_str.split(",") if t.strip()] or None

    args = {"query": query, "limit": limit, "message_id": _message_id, "min_similarity": 0}
    if tags:
        args["tags"] = tags
    if memory_types:
        args["memory_types"] = memory_types

    _info("Searching...")
    result = await tools["search_memory"].handler(args)

    if "error" in result:
        _fail(f"Error: {result['error']}")
        return

    entries = result.get("results", [])
    if not entries:
        _info("No results found.")
        return

    _ok(f"{len(entries)} result(s) found:")
    for i, entry in enumerate(entries):
        _print_memory(entry, index=i)


async def cmd_create(tools: dict) -> None:
    """Create a new memory entry."""
    title = input(f"  {CYAN}Title: {RESET}").strip()
    content = input(f"  {CYAN}Content: {RESET}").strip()
    if not content:
        _fail("Content is required.")
        return

    memory_type = input(f"  {CYAN}Type (e.g. thesis, note, observation): {RESET}").strip() or None
    source = input(f"  {CYAN}Source (optional): {RESET}").strip() or None
    tags_str = input(f"  {CYAN}Tags (comma-separated, optional): {RESET}").strip()
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] or None

    args: dict = {"content": content, "message_id": _message_id}
    if title:
        args["title"] = title
    if memory_type:
        args["memory_type"] = memory_type
    if source:
        args["source"] = source
    if tags:
        args["tags"] = tags

    _info("Creating memory...")
    result = await tools["memory_create"].handler(args)

    if "error" in result:
        _fail(f"Error: {result['error']}")
    else:
        _ok(f"Memory created — ID: {result.get('memory_id')}")
        mem = result.get("memory")
        if mem:
            _print_memory(mem)


async def cmd_get(tools: dict) -> None:
    """Retrieve a memory by its ID."""
    mid = input(f"  {CYAN}Memory ID (UUID): {RESET}").strip()
    if not mid:
        return

    _info("Fetching...")
    result = await tools["memory_get_by_id"].handler({"memory_id": mid, "message_id": _message_id})

    if "error" in result:
        _fail(f"Error: {result['error']}")
    else:
        entry = result.get("entry", result)
        _print_memory(entry)


async def cmd_update(tools: dict) -> None:
    """Update an existing memory entry."""
    mid = input(f"  {CYAN}Memory ID (UUID): {RESET}").strip()
    if not mid:
        return

    # Show current state first
    current = await tools["memory_get_by_id"].handler({"memory_id": mid, "message_id": _message_id})
    if "error" in current:
        _fail(f"Error: {current['error']}")
        return
    _info("Current entry:")
    _print_memory(current.get("entry", current))

    reason = input(f"\n  {CYAN}Reason for update: {RESET}").strip()
    if not reason:
        _fail("A reason is required.")
        return

    new_content = input(f"  {CYAN}New content (leave empty to keep): {RESET}").strip() or None
    tags_str = input(f"  {CYAN}New tags (comma-separated, leave empty to keep): {RESET}").strip()
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] or None

    args: dict = {"memory_id": mid, "reason": reason, "message_id": _message_id}
    if new_content:
        args["content"] = new_content
    if tags:
        args["tags"] = tags

    _info("Updating...")
    result = await tools["memory_update"].handler(args)

    if "error" in result:
        _fail(f"Error: {result['error']}")
    else:
        _ok(f"Memory {mid} updated.")
        mem = result.get("memory")
        if mem:
            _print_memory(mem)


async def cmd_deprecate(tools: dict) -> None:
    """Deprecate a memory entry."""
    mid = input(f"  {CYAN}Memory ID (UUID): {RESET}").strip()
    if not mid:
        return

    # Show current state first
    current = await tools["memory_get_by_id"].handler({"memory_id": mid, "message_id": _message_id})
    if "error" in current:
        _fail(f"Error: {current['error']}")
        return
    _info("Entry to deprecate:")
    _print_memory(current.get("entry", current))

    confirm = input(f"\n  {YELLOW}Deprecate this entry? [y/N]: {RESET}").strip().lower()
    if confirm not in ("y", "yes"):
        _info("Cancelled.")
        return

    reason = input(f"  {CYAN}Reason: {RESET}").strip()
    if not reason:
        _fail("A reason is required.")
        return

    _info("Deprecating...")
    result = await tools["memory_deprecate"].handler({"memory_id": mid, "reason": reason, "message_id": _message_id})

    if "error" in result:
        _fail(f"Error: {result['error']}")
    else:
        _ok(f"Memory {mid} deprecated.")


# ── Main loop ────────────────────────────────────────────────────────────
COMMANDS = {
    "search": ("Search memories by query", cmd_search),
    "create": ("Create a new memory", cmd_create),
    "get": ("Get a memory by ID", cmd_get),
    "update": ("Update an existing memory", cmd_update),
    "deprecate": ("Deprecate a memory", cmd_deprecate),
}


async def _main() -> None:
    _header("Memory Manager")

    # ── Init DB ──
    from db.database import init_db
    from db.db_tools import DBTools

    _info("Initializing database...")
    try:
        db = init_db()
        db.create_tables()
        dbTools = DBTools()
        _ok("Database ready.")
    except Exception as exc:
        _fail(f"Database init failed: {exc}")
        return

    # ── Create a dummy run + message for access logging ──
    global _message_id
    try:
        run_id = dbTools.start_run("memory_manager", "manual", "n/a")
        _message_id = str(dbTools.add_message(run_id, "system", "memory_manager interactive session"))
        _ok(f"Test run created (message_id={_message_id}).")
    except Exception as exc:
        _fail(f"Could not create test run: {exc}")
        return

    # ── Load memory tools ──
    from llm.tools.base import get_tools

    all_tools = get_tools()
    memory_tool_names = ["search_memory", "memory_create", "memory_get_by_id", "memory_update", "memory_deprecate"]
    memory_tools = {k: all_tools[k] for k in memory_tool_names if k in all_tools}

    missing = set(memory_tool_names) - set(memory_tools.keys())
    if missing:
        _fail(f"Missing tools: {', '.join(missing)}")
        return

    _ok(f"Memory tools loaded: {', '.join(memory_tools.keys())}")

    # ── Menu loop ──
    print(f"\n  {CYAN}Commands:{RESET}")
    for cmd, (desc, _) in COMMANDS.items():
        print(f"    {BOLD}{cmd:<12}{RESET} {desc}")
    print(f"    {BOLD}{'quit':<12}{RESET} Exit")

    while True:
        try:
            choice = input(f"\n{BOLD}{GREEN}memory> {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice in ("quit", "exit", "q"):
            break

        if choice in COMMANDS:
            _, handler = COMMANDS[choice]
            try:
                await handler(memory_tools)
            except Exception as exc:
                _fail(f"Unexpected error: {exc}")
        elif choice == "":
            continue
        else:
            _fail(f"Unknown command: {choice}")
            _info(f"Available: {', '.join(COMMANDS.keys())}, quit")

    print(f"\n{BOLD}{YELLOW}Goodbye.{RESET}")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
