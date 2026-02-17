"""
Interactive tool runner — execute any registered ZETA tool from the CLI.

Usage:
    python test_tools/tool_runner.py

Steps performed automatically:
  1. Database connection + table creation
  2. Embedding model loading + DBTools singleton init
  3. IBKR connection (via ib_async)
  4. Tool auto-discovery (import of all tool modules)

Then an interactive menu lets you pick a tool, fill its arguments, and run it.
A random run_id / message_id are created so DB logging does not crash.
"""

import asyncio
import json
import os
import sys
import uuid
from typing import Any, Dict

# ── Path setup ───────────────────────────────────────────────────────────
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "script"))

from dotenv import load_dotenv

load_dotenv(os.path.join(_root, ".env"))

# ── Colour helpers ───────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}✓ {msg}{RESET}")


def _fail(msg: str) -> None:
    print(f"  {RED}✗ {msg}{RESET}")


def _info(msg: str) -> None:
    print(f"  {CYAN}ℹ {msg}{RESET}")


def _header(title: str) -> None:
    print(f"\n{BOLD}{YELLOW}{'═' * 55}")
    print(f"  {title}")
    print(f"{'═' * 55}{RESET}")


# ── Initialisation helpers ───────────────────────────────────────────────

def init_database():
    """Initialise the database connection and create tables."""
    from db.database import init_db

    _header("Database")
    try:
        db = init_db()
        db.create_tables()
        _ok("Database connected and tables ready.")
        return db
    except Exception as exc:
        _fail(f"Database init failed: {exc}")
        raise


def init_embedding_and_dbtools():
    """Load the embedding model and create the DBTools singleton."""
    from config import get as cfg_get
    from db.db_tools import DBTools
    from sentence_transformers import SentenceTransformer

    _header("Embedding model + DBTools")
    model_name = cfg_get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
    _info(f"Loading model: {model_name} …")
    embed_model = SentenceTransformer(model_name)
    embedding_fn = lambda text: embed_model.encode(text).tolist()
    DBTools(embedding_function=embedding_fn)
    _ok(f"DBTools initialised (embedding dim={embed_model.get_sentence_embedding_dimension()}).")


async def init_ibkr():
    """Connect to IBKR TWS / Gateway."""
    from config import get as cfg_get
    from ibkr.ibTools import init_ib_connection

    _header("IBKR connection")
    dry_run = cfg_get("dry_run", True)
    _info(f"dry_run = {dry_run}")
    ib = await init_ib_connection(dry_run)
    _ok("IBKR connected.")
    return ib


def discover_tools():
    """Import all tool modules so TOOL_REGISTRY is populated."""
    from llm.tools.base import get_tools
    # get_tools() triggers _auto_import_tools via module init
    tools = get_tools()
    return tools


# ── Argument helpers ─────────────────────────────────────────────────────

def _prompt_value(name: str, field_info: dict) -> Any:
    """Prompt the user for a single argument value."""
    field_type = field_info.get("type", "string")
    description = field_info.get("description", "")
    default = field_info.get("default")
    enum_values = field_info.get("enum")

    # Build prompt string
    prompt_parts = [f"  {CYAN}{name}{RESET}"]
    if description:
        prompt_parts.append(f" {DIM}({description}){RESET}")
    if enum_values:
        prompt_parts.append(f" [{', '.join(str(e) for e in enum_values)}]")
    if default is not None:
        prompt_parts.append(f" [{YELLOW}default: {default}{RESET}]")
    prompt_parts.append(": ")
    prompt_str = "".join(prompt_parts)

    raw = input(prompt_str).strip()

    # Use default if empty
    if raw == "" and default is not None:
        return default
    if raw == "" and "null" in str(field_info.get("anyOf", "")):
        return None
    if raw == "":
        # Check if field is optional (anyOf with null)
        any_of = field_info.get("anyOf", [])
        for sub in any_of:
            if sub.get("type") == "null":
                return None

    # Type coercion
    if field_type == "integer":
        return int(raw)
    elif field_type == "number":
        return float(raw)
    elif field_type == "boolean":
        return raw.lower() in ("true", "1", "yes", "y")
    elif field_type == "array":
        # Accept JSON array or comma-separated values
        if raw.startswith("["):
            return json.loads(raw)
        return [v.strip() for v in raw.split(",") if v.strip()]
    elif field_type == "object":
        return json.loads(raw)

    return raw


def _is_field_required(name: str, schema: dict) -> bool:
    return name in schema.get("required", [])


def _resolve_type(field_info: dict) -> dict:
    """Resolve anyOf / allOf wrappers to get the actual type info."""
    if "anyOf" in field_info:
        # Pick first non-null type
        for sub in field_info["anyOf"]:
            if sub.get("type") != "null":
                merged = {**field_info, **sub}
                merged.pop("anyOf", None)
                return merged
    return field_info


def collect_args(schema: dict) -> Dict[str, Any]:
    """Interactively collect arguments based on a Pydantic JSON schema."""
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    if not properties:
        print(f"  {DIM}(no arguments){RESET}")
        return {}

    args: Dict[str, Any] = {}
    print()

    # Required arguments first
    for name in required:
        if name not in properties:
            continue
        field_info = _resolve_type(properties[name])
        value = _prompt_value(name, field_info)
        if value is not None and value != "":
            args[name] = value

    # Optional arguments
    optional = [k for k in properties if k not in required]
    if optional:
        print(f"\n  {DIM}Optional arguments (press Enter to skip):{RESET}")
        for name in optional:
            field_info = _resolve_type(properties[name])
            value = _prompt_value(name, field_info)
            if value is not None and value != "":
                args[name] = value

    return args


# ── Main interactive loop ────────────────────────────────────────────────

async def interactive_loop(tools: dict):
    """Main REPL: pick a tool → fill args → run → show result."""
    from db.db_tools import DBTools

    sorted_names = sorted(tools.keys())

    while True:
        _header("Available tools")
        for idx, name in enumerate(sorted_names, 1):
            desc = tools[name].description
            # Truncate long descriptions
            if len(desc) > 70:
                desc = desc[:67] + "…"
            print(f"  {BOLD}{idx:3d}{RESET}. {GREEN}{name}{RESET}  {DIM}{desc}{RESET}")
        print(f"  {BOLD}  0{RESET}. {RED}Quit{RESET}")
        print()

        raw = input(f"{BOLD}Choose a tool (number or name): {RESET}").strip()
        if raw in ("0", "q", "quit", "exit"):
            break

        # Resolve selection
        selected_name: str | None = None
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(sorted_names):
                selected_name = sorted_names[idx - 1]
        else:
            if raw in tools:
                selected_name = raw
            else:
                # Fuzzy: find tools containing the input
                matches = [n for n in sorted_names if raw.lower() in n.lower()]
                if len(matches) == 1:
                    selected_name = matches[0]
                elif matches:
                    print(f"  {YELLOW}Ambiguous — did you mean one of: {', '.join(matches)}?{RESET}")
                    continue

        if selected_name is None:
            _fail("Invalid selection.")
            continue

        tool_spec = tools[selected_name]
        _header(f"Tool: {selected_name}")
        print(f"  {tool_spec.description}\n")

        # Show argument schema
        schema = tool_spec.args_model.model_json_schema()
        args = collect_args(schema)

        # Inject random message_id for DB logging (memory tools need it)
        dummy_message_id = uuid.uuid4()
        args["message_id"] = dummy_message_id

        print(f"\n  {DIM}message_id (auto): {dummy_message_id}{RESET}")
        print(f"\n  {CYAN}Executing {selected_name}…{RESET}")

        try:
            result = await tool_spec.handler(args)
            print(f"\n{GREEN}{'─' * 55}")
            print(f"  Result:{RESET}")
            print(json.dumps(result, indent=2, default=str))
            print(f"{GREEN}{'─' * 55}{RESET}")
        except Exception as exc:
            _fail(f"Execution failed: {exc}")

        print()


# ── Entry point ──────────────────────────────────────────────────────────

async def main():
    _header("ZETA Tool Runner")

    ib = None
    try:
        # 1. Database
        init_database()

        # 2. Embedding + DBTools
        init_embedding_and_dbtools()

        # 3. IBKR
        ib = await init_ibkr()

        # 4. Discover tools
        _header("Tool discovery")
        tools = discover_tools()
        _ok(f"{len(tools)} tools discovered.")

        # 5. Create a dummy run so tool-call DB logging works
        from db.db_tools import DBTools
        db_tools = DBTools.get_instance()
        dummy_run_id = db_tools.start_run("test_tool_runner", "manual", "n/a")
        dummy_message_id = db_tools.add_message(dummy_run_id, "system", "[tool_runner] interactive session")
        _info(f"Dummy run_id:     {dummy_run_id}")
        _info(f"Dummy message_id: {dummy_message_id}")

        # 6. Interactive loop
        await interactive_loop(tools)

        # Mark run as completed
        db_tools.end_run(dummy_run_id, "completed")

    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted.{RESET}")
    except Exception as exc:
        _fail(f"Fatal: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        if ib and ib.isConnected():
            _info("Disconnecting IBKR…")
            ib.disconnect()
        print(f"\n{DIM}Bye.{RESET}")


if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
