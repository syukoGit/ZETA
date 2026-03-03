"""
Interactive tool runner for manually executing one registered ZETA tool.

Features:
- Lists all registered tools (run + review).
- Asks for tool parameters interactively.
- Uses hybrid input strategy:
  - guided prompts for simple scalar fields
  - JSON input for complex fields (nested objects/lists)
- Validates arguments with each tool's Pydantic schema.
- Injects a test `message_id` automatically for memory/audit compatibility.
- Adds an extra safety gate for live IBKR side-effect tools.

Usage:
	python test_tools/tool_runner.py
	python test_tools/tool_runner.py --tool get_quote
	python test_tools/tool_runner.py --live
"""

import argparse
import asyncio
import importlib
import json
import os
import sys
from types import UnionType
from typing import Any, Dict, Optional, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticUndefined

# Ensure the project root and script/ are on sys.path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "script"))

from dotenv import load_dotenv

from utils.json_utils import dumps_json

load_dotenv(os.path.join(_root, ".env"))


def _bootstrap_module_aliases() -> None:
	"""Expose legacy top-level `db.*` names as aliases to `script.db.*` modules.

	This lets tools importing `db.*` work in `test_tools` context while keeping
	the real package execution path under `script.db.*`.
	"""
	module_pairs = {
		"db": "script.db",
		"db.models": "script.db.models",
		"db.time_utils": "script.db.time_utils",
		"db.embedding_model": "script.db.embedding_model",
		"db.database": "script.db.database",
		"db.db_tools": "script.db.db_tools",
		"db.repositories": "script.db.repositories",
		"db.repositories.base_repository": "script.db.repositories.base_repository",
		"db.repositories.memory_repository": "script.db.repositories.memory_repository",
		"db.repositories.message_repository": "script.db.repositories.message_repository",
		"db.repositories.run_repository": "script.db.repositories.run_repository",
		"db.repositories.tool_call_repository": "script.db.repositories.tool_call_repository",
	}

	for alias, target in module_pairs.items():
		if alias in sys.modules:
			continue
		sys.modules[alias] = importlib.import_module(target)

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


def _warn(msg: str) -> None:
	print(f"  {YELLOW}{msg}{RESET}")


def _header(title: str) -> None:
	print(f"\n{BOLD}{YELLOW}{'═' * 58}")
	print(f"  {title}")
	print(f"{'═' * 58}{RESET}")


def _prompt_yes_no(label: str, default: bool = False) -> bool:
	suffix = "[Y/n]" if default else "[y/N]"
	while True:
		choice = input(f"  {YELLOW}{label} {suffix}: {RESET}").strip().lower()
		if not choice:
			return default
		if choice in ("y", "yes"):
			return True
		if choice in ("n", "no"):
			return False
		_fail("Invalid input, expected yes/no.")


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
			raise ValueError(f"Value must be one of: {', '.join(str(v) for v in allowed)}")
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
		print(f"\n  {BOLD}Provide tool parameters:{RESET}")

		for field_name, field_info in fields.items():
			required = field_info.is_required()
			annotation = field_info.annotation
			description = field_info.description or ""
			default_txt = _format_default(field_info)
			req_txt = "required" if required else "optional"

			if description:
				print(f"  {DIM}{field_name} ({req_txt}{default_txt}) — {description}{RESET}")
			else:
				print(f"  {DIM}{field_name} ({req_txt}{default_txt}){RESET}")

			while True:
				try:
					if _is_complex_field(annotation):
						raw = input(
							f"  {CYAN}{field_name}{RESET} as JSON"
							f"{DIM} (empty to skip if optional){RESET}: "
						).strip()
						if not raw:
							if required:
								_fail("This field is required.")
								continue
							break
						collected[field_name] = json.loads(raw)
						break

					if _is_list_of_simple(annotation):
						raw = input(
							f"  {CYAN}{field_name}{RESET} as comma-separated values"
							f"{DIM} (empty to skip if optional){RESET}: "
						).strip()
						if not raw:
							if required:
								_fail("This field is required.")
								continue
							break
						collected[field_name] = _parse_list_of_simple(raw, annotation)
						break

					raw = input(
						f"  {CYAN}{field_name}{RESET}"
						f"{DIM} (empty to skip if optional){RESET}: "
					).strip()
					if not raw:
						if required:
							_fail("This field is required.")
							continue
						break

					collected[field_name] = _parse_simple_scalar(raw, annotation)
					break

				except ValueError as exc:
					_fail(str(exc))
				except json.JSONDecodeError as exc:
					_fail(f"Invalid JSON: {exc}")

		try:
			model.model_validate(collected)
			return collected
		except ValidationError as exc:
			_fail("Validation error:")
			for err in exc.errors():
				loc = ".".join(str(part) for part in err.get("loc", []))
				msg = err.get("msg", "Invalid value")
				print(f"    {RED}- {loc}: {msg}{RESET}")
			if not _prompt_yes_no("Retry parameter entry?", default=True):
				raise


def _merge_tools(run_tools: Dict[str, Any], review_tools: Dict[str, Any]) -> Dict[str, Any]:
	merged = dict(review_tools)
	merged.update(run_tools)
	return merged


def _choose_tool_interactive(tools: Dict[str, Any], run_names: set[str], review_names: set[str]) -> Optional[str]:
	tool_names = sorted(tools.keys())
	if not tool_names:
		return None

	_header("Available Tools")
	for idx, name in enumerate(tool_names):
		tags = []
		if name in run_names:
			tags.append("run")
		if name in review_names:
			tags.append("review")
		tag_txt = f" [{'/'.join(tags)}]" if tags else ""
		desc = tools[name].description
		print(f"  {BOLD}{idx:>2}{RESET}  {CYAN}{name}{RESET}{DIM}{tag_txt}{RESET} — {desc}")

	while True:
		choice = input(
			f"\n{BOLD}{GREEN}tool> {RESET}"
			f"Type index/name, or 'quit': "
		).strip()
		if not choice:
			continue
		if choice.lower() in ("q", "quit", "exit"):
			return None

		if choice.isdigit():
			idx = int(choice)
			if 0 <= idx < len(tool_names):
				return tool_names[idx]
			_fail(f"Index out of range (0..{len(tool_names) - 1}).")
			continue

		if choice in tools:
			return choice

		_fail("Unknown tool name.")


async def _main() -> None:
	parser = argparse.ArgumentParser(description="Interactive ZETA tool runner")
	parser.add_argument("--tool", type=str, help="Tool name to preselect")
	parser.add_argument("--dry-run", action="store_true", help="Force dry_run mode for IBKR connection")
	parser.add_argument("--live", action="store_true", help="Force live mode for IBKR connection")
	args = parser.parse_args()

	_header("Tool Runner")

	_bootstrap_module_aliases()

	from config import config
	from db.database import init_db
	from db.db_tools import DBTools
	from ibkr.ibTools import init_ib_connection
	from llm.tools.base import get_tools

	# Runtime config
	dry_run = config().dry_run
	if args.dry_run and args.live:
		_fail("Use either --dry-run or --live, not both.")
		return
	if args.dry_run:
		dry_run = True
	if args.live:
		dry_run = False

	# ── Initialize DB + test message context ──
	_info("Initializing database...")
	try:
		db = init_db()
		db.create_tables()
		db_tools = DBTools()
		_ok("Database ready.")
	except Exception as exc:
		_fail(f"Database init failed: {exc}")
		return

	try:
		run_id = db_tools.start_run("tool_runner", "manual", "n/a")
		message_id = db_tools.add_message(run_id, "system", "tool_runner interactive session")
		_ok(f"Test run created (message_id={message_id}).")
	except Exception as exc:
		_fail(f"Could not create test run/message: {exc}")
		return

	# ── Load tools (run + review) ──
	run_tools = get_tools("run")
	review_tools = get_tools("review")
	all_tools = _merge_tools(run_tools, review_tools)

	if not all_tools:
		_fail("No tools found in registry.")
		return

	_ok(f"Loaded {len(all_tools)} tool(s): {len(run_tools)} run + {len(review_tools)} review")

	ib_tools = {
		"get_cash_balance",
		"preview_order",
		"place_order",
		"modify_order",
		"get_volatility_metrics",
		"get_trade_history",
		"get_quote",
		"get_positions",
		"get_pnl",
		"get_open_trades",
		"get_history",
		"cancel_order",
	}
	side_effect_ib_tools = {"place_order", "modify_order", "cancel_order"}

	ib_ready = False

	while True:
		if args.tool:
			tool_name = args.tool
			args.tool = None
			if tool_name not in all_tools:
				_fail(f"Unknown tool: {tool_name}")
				_info("Switching to interactive selection.")
				tool_name = _choose_tool_interactive(all_tools, set(run_tools.keys()), set(review_tools.keys()))
		else:
			tool_name = _choose_tool_interactive(all_tools, set(run_tools.keys()), set(review_tools.keys()))

		if not tool_name:
			break

		spec = all_tools[tool_name]
		_header(f"Execute: {tool_name}")
		_info(spec.description)

		# Lazy IB connection only when required
		if tool_name in ib_tools and not ib_ready:
			_info(f"Connecting to IBKR (dry_run={dry_run})...")
			try:
				await init_ib_connection(dry_run)
				ib_ready = True
				_ok("IBKR connected.")
			except Exception as exc:
				_fail(f"IBKR connection failed: {exc}")
				_info("Skipping this tool execution.")
				if not _prompt_yes_no("Pick another tool?", default=True):
					break
				continue

		# Safety gate for side effects in live mode
		if tool_name in side_effect_ib_tools and not dry_run:
			_warn("LIVE mode detected for IBKR side-effect tool.")
			if not _prompt_yes_no("Confirm you want to continue in LIVE mode", default=False):
				_info("Execution cancelled.")
				continue
			typed = input(f"  {YELLOW}Type exact tool name to confirm ({tool_name}): {RESET}").strip()
			if typed != tool_name:
				_fail("Confirmation failed. Execution cancelled.")
				continue

		# Collect and validate arguments
		try:
			raw_args = _collect_args_for_model(spec.args_model)
		except ValidationError:
			_info("Execution cancelled after validation failure.")
			continue

		# Validate once more and build handler payload
		try:
			validated = spec.args_model.model_validate(raw_args).model_dump()
		except ValidationError as exc:
			_fail(f"Validation failed unexpectedly: {exc}")
			continue

		handler_args = dict(validated)
		handler_args["message_id"] = message_id

		print(f"\n  {BOLD}Final arguments:{RESET}")
		print(f"  {DIM}{dumps_json(handler_args, indent=2)}{RESET}")

		if not _prompt_yes_no("Execute this tool call", default=True):
			_info("Cancelled.")
			continue

		_info("Running tool...")
		try:
			result = await spec.handler(handler_args)
			_ok("Tool executed successfully.")
			print(f"\n  {BOLD}Result:{RESET}")
			print(f"  {dumps_json(result, indent=2)}")
		except Exception as exc:
			_fail(f"Tool execution failed: {exc}")

		if not _prompt_yes_no("Run another tool", default=True):
			break

	print(f"\n{BOLD}{YELLOW}Goodbye.{RESET}")


def main() -> None:
	asyncio.run(_main())


if __name__ == "__main__":
	main()
