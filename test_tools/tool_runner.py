from tools_utils.init import init

init()

import asyncio
import json
from types import UnionType
from typing import Any, Dict, Optional, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticUndefined

from llm.tools.base import ToolSpec, get_tools
from test_tools.tools_utils.check_connections import init_database, init_ibkr
from test_tools.tools_utils.display import *
from utils.json_utils import dumps_json


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin is UnionType or str(origin) in ("typing.Union", "types.UnionType"):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _is_list_of_simple(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin is not list:
        return False
    args = get_args(annotation)
    if not args:
        return False
    inner = args[0]
    inner, _ = _unwrap_optional(inner)
    return inner in (str, int, float, bool)


def _is_complex_field(annotation: Any) -> bool:
    annotation, _ = _unwrap_optional(annotation)
    origin = get_origin(annotation)

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return True

    if _is_list_of_simple(annotation):
        return False

    if origin in (list, dict, tuple, set):
        return True

    return False


def _parse_bool(raw: str) -> bool:
    val = raw.strip().lower()
    if val in ("true", "t", "1", "yes", "y"):
        return True
    if val in ("false", "f", "0", "no", "n"):
        return False
    raise ValueError("Expected a boolean (true/false)")


def _parse_simple_scalar(raw: str, annotation: Any) -> Any:
    annotation, _ = _unwrap_optional(annotation)

    origin = get_origin(annotation)
    if str(origin) == "typing.Literal":
        allowed = get_args(annotation)
        if raw not in [str(v) for v in allowed]:
            raise ValueError(
                f"Value must be one of: {', '.join(str(v) for v in allowed)}"
            )
        for candidate in allowed:
            if str(candidate) == raw:
                return candidate
        return raw

    if annotation is str:
        return raw
    if annotation is int:
        return int(raw)
    if annotation is float:
        return float(raw)
    if annotation is bool:
        return _parse_bool(raw)

    return raw


def _parse_list_of_simple(raw: str, annotation: Any) -> list[Any]:
    args = get_args(annotation)
    inner = args[0] if args else str
    inner, _ = _unwrap_optional(inner)
    if not raw.strip():
        return []
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return [_parse_simple_scalar(p, inner) for p in parts]


def _format_default(field_info: Any) -> str:
    if field_info.default is PydanticUndefined:
        return ""
    return f" default={field_info.default}"


def _collect_args_for_model(model: type[BaseModel]) -> Dict[str, Any]:
    fields = model.model_fields
    if not fields:
        return {}

    while True:
        collected: Dict[str, Any] = {}
        message(f"  Provide tool parametters: ")

        for field_name, field_info in fields.items():
            required = field_info.is_required()
            annotation = field_info.annotation
            description = field_info.description or ""
            default_txt = _format_default(field_info)
            req_txt = "required" if required else "optional"
            empty_for_optional_text = (
                " (empty to skip if optional)" if not required else ""
            )

            if description:
                message(f"  {DIM}{field_name} ({req_txt}{default_txt}) — {description}")
            else:
                message(f"  {DIM}{field_name} ({req_txt}{default_txt})")

            while True:
                try:
                    if _is_complex_field(annotation):
                        raw = prompt(
                            f"  {CYAN}{field_name}{RESET}{DIM} as JSON{empty_for_optional_text}{RESET}: "
                        )

                        if not raw:
                            if required:
                                fail("This field is required.")
                                continue
                            break

                        collected[field_name] = json.loads(raw)
                        break

                    if _is_list_of_simple(annotation):
                        raw = prompt(
                            f"  {CYAN}{field_name}{RESET}{DIM} as comma-separated values{empty_for_optional_text}{RESET}: "
                        )

                        if not raw:
                            if required:
                                fail("This field is required.")
                                continue
                            break
                        collected[field_name] = _parse_list_of_simple(raw, annotation)
                        break

                    raw = prompt(
                        f"  {CYAN}{field_name}{RESET}{DIM}{empty_for_optional_text}{RESET}: "
                    )

                    if not raw:
                        if required:
                            fail("This field is required.")
                            continue
                        break

                    collected[field_name] = _parse_simple_scalar(raw, annotation)
                    break

                except ValueError as exc:
                    fail(str(exc))
                except json.JSONDecodeError as exc:
                    fail(f"Invalid JSON: {exc}")

        try:
            model.model_validate(collected)
            return collected
        except ValidationError as exc:
            fail("Validation error:")
            for err in exc.errors():
                loc = ".".join(str(part) for part in err.get("loc", []))
                msg = err.get("msg", "Invalid value")
                fail(f"    - {loc}: {msg}")
            if not prompt_yes_no("Retry parameter entry?", default=True):
                raise


def _choose_tool_interactive(tools: Dict[str, ToolSpec]) -> Optional[str]:
    tool_names = sorted(tools.keys())
    if not tool_names:
        return None

    header("Available Tools")

    for i, tool_name in enumerate(tool_names):
        message(f"  {CYAN}{i}{RESET}: {tool_name} - {tools[tool_name].description}")

    while True:
        choice = prompt(
            f"\n{BOLD}{GREEN} tool> {RESET}{DIM}Type index/name, or 'quit': "
        )

        if not choice:
            continue
        if choice.lower() in ("q", "quit", "exit"):
            return None

        if choice.isdigit():
            idx = int(choice)
            if 0 <= idx < len(tool_names):
                return tool_names[idx]
            fail(f"Index out of range (0..{len(tool_names) - 1}).")
            continue

        if choice in tools:
            return choice

        fail("Unknown tool name.")


async def _main() -> None:
    header("Tool Runner")

    message_id = init_database()

    if message_id is None:
        return

    await init_ibkr()

    # ── Load tools (run + review) ──
    tools = get_tools("all")

    if not tools:
        fail("No tools found in registry.")
        return

    ok(f"Loaded {len(tools)} tool(s)")

    while True:
        tool_name = _choose_tool_interactive(tools)

        if not tool_name:
            break

        spec = tools[tool_name]
        header(f"Execute: {tool_name}")
        info(spec.description)

        # Collect and validate arguments
        try:
            raw_args = _collect_args_for_model(spec.args_model)
        except ValidationError:
            info("Execution cancelled after validation failure.")
            continue

        # Validate once more and build handler payload
        try:
            validated = spec.args_model.model_validate(raw_args).model_dump()
        except ValidationError as exc:
            fail(f"Validation failed unexpectedly: {exc}")
            continue

        handler_args = dict(validated)
        handler_args["message_id"] = message_id

        info(f"\n  {BOLD}Final arguments:")
        message(f"  {DIM}{dumps_json(handler_args, indent=2)}")

        if not prompt_yes_no("\nExecute this tool call", default=True):
            info("Cancelled.")
            continue

        info("Running tool...")
        try:
            result = await spec.handler(handler_args)
            ok("Tool executed successfully.")
            info(f"\n  {BOLD}Result:")
            message(f"  {DIM}{dumps_json(result, indent=2)}")
        except Exception as exc:
            fail(f"Tool execution failed: {exc}")

        if not prompt_yes_no("\nRun another tool", default=True):
            break

    message(f"\n{BOLD}{YELLOW}Goodbye.")


if __name__ == "__main__":
    asyncio.run(_main())
