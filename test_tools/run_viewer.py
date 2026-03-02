"""
Interactive run viewer — browse runs and inspect their full message history.

Usage:
    python test_tools/run_viewer.py
    python test_tools/run_viewer.py --run <uuid>
    python test_tools/run_viewer.py --limit 20
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from uuid import UUID

# Ensure the project root and script/ are on sys.path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "script"))

from utils.json_utils import dumps_json

from dotenv import load_dotenv

load_dotenv(os.path.join(_root, ".env"))

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
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
    width = 62
    print(f"\n{BOLD}{YELLOW}{'═' * width}")
    print(f"  {title}")
    print(f"{'═' * width}{RESET}")


def _subheader(title: str) -> None:
    width = 56
    print(f"\n{BOLD}{CYAN}{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}{RESET}")


def _separator(char: str = "·", width: int = 56) -> None:
    print(f"  {DIM}{char * width}{RESET}")


# ── Formatting helpers ────────────────────────────────────────────────────────
_STATUS_COLOUR = {
    "running": CYAN,
    "completed": GREEN,
    "failed": RED,
    "cancelled": YELLOW,
}

_ROLE_COLOUR = {
    "system": DIM + YELLOW,
    "user": BLUE,
    "assistant": GREEN,
    "tool_result": MAGENTA,
}


def _status_str(status: str | None) -> str:
    colour = _STATUS_COLOUR.get(status or "", DIM)
    return f"{colour}{status or '?'}{RESET}"


def _role_str(role: str | None) -> str:
    colour = _ROLE_COLOUR.get(role or "", DIM)
    return f"{BOLD}{colour}{(role or '?').upper():<12}{RESET}"


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return f"{DIM}—{RESET}"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_duration(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return f"{DIM}—{RESET}"
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    secs = int((end - start).total_seconds())
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m{secs % 60:02d}s"


def _short_id(uid: UUID | None) -> str:
    if uid is None:
        return "?"
    return str(uid)[:8]


def _wrap_text(text: str, indent: int = 6, max_width: int = 100) -> str:
    """Indent every line of text."""
    prefix = " " * indent
    lines = text.splitlines()
    return "\n".join(prefix + line for line in lines)


# ── Run listing ───────────────────────────────────────────────────────────────
def _print_run_row(index: int, run, msg_count: int) -> None:
    idx_str = f"{BOLD}{index:>3}.{RESET}"
    short = f"{DIM}{_short_id(run.id)}…{RESET}"
    status = _status_str(run.status)
    started = _fmt_dt(run.started_at)
    duration = _fmt_duration(run.started_at, run.ended_at)
    msgs = f"{CYAN}{msg_count} msg{'s' if msg_count != 1 else ''}{RESET}"
    model_info = f"{DIM}{run.provider}/{run.model}{RESET}"
    trigger = f"{YELLOW}{run.trigger_type or '?'}{RESET}"

    print(f"  {idx_str} [{short}]  {status:<30}  {trigger:<20}  {started}  {duration:>8}  {msgs}  {model_info}")


def _list_runs(session, limit: int) -> list:
    from db.models import Message, Run

    runs = (
        session.query(Run)
        .order_by(Run.started_at.desc())
        .limit(limit)
        .all()
    )

    # Count messages per run in one shot
    from sqlalchemy import func

    counts_q = (
        session.query(Message.run_id, func.count(Message.id).label("cnt"))
        .filter(Message.run_id.in_([r.id for r in runs]))
        .group_by(Message.run_id)
        .all()
    )
    count_map = {row.run_id: row.cnt for row in counts_q}

    _header(f"Runs  (newest {limit} shown)")
    print(
        f"\n  {BOLD}{'#':>4}  {'ID':9}  {'Status':<20}  "
        f"{'Trigger':<20}  {'Started (UTC)':>23}  {'Dur':>8}  {'Msgs'}{RESET}"
    )
    _separator("─", 100)

    for i, run in enumerate(runs):
        _print_run_row(i + 1, run, count_map.get(run.id, 0))

    return runs


# ── Message display ───────────────────────────────────────────────────────────
def _print_tool_call(tc, indent: int = 8) -> None:
    pad = " " * indent
    status_colour = GREEN if tc.status == "completed" else RED if tc.status == "failed" else CYAN
    print(
        f"{pad}{BOLD}{MAGENTA}⚙  {tc.tool_name}{RESET}  "
        f"{status_colour}[{tc.status or '?'}]{RESET}  "
        f"{DIM}{_fmt_dt(tc.executed_at)}{RESET}"
    )
    print(f"{pad}{DIM}id: {tc.id}{RESET}")

    if tc.input_payload:
        try:
            payload_str = dumps_json(tc.input_payload, indent=2)
        except Exception:
            payload_str = str(tc.input_payload)
        print(f"{pad}{DIM}input:{RESET}")
        for line in payload_str.splitlines():
            print(f"{pad}  {DIM}{line}{RESET}")

    if tc.output_payload:
        try:
            out_str = dumps_json(tc.output_payload, indent=2)
        except Exception:
            out_str = str(tc.output_payload)
        print(f"{pad}{DIM}output:{RESET}")
        for line in out_str.splitlines():
            print(f"{pad}  {DIM}{line}{RESET}")


def _print_message(msg, show_full: bool = False) -> None:
    role_str = _role_str(msg.role)
    seq = f"{DIM}#{msg.sequence_index}{RESET}" if msg.sequence_index is not None else ""
    ts = f"{DIM}{_fmt_dt(msg.created_at)}{RESET}"
    id_str = f"{DIM}id: {msg.id}{RESET}"

    print(f"\n  {role_str}  {seq}  {ts}")
    print(f"    {id_str}")

    content = msg.content or ""
    if content:
        max_chars = None if show_full else 800
        display = content if (max_chars is None or len(content) <= max_chars) else content[:max_chars] + f"\n{DIM}… ({len(content) - max_chars} more chars — use 'full' mode to expand){RESET}"
        for line in display.splitlines():
            print(f"      {line}")

    if msg.tool_calls:
        print(f"\n    {BOLD}{MAGENTA}Tool calls ({len(msg.tool_calls)}):{RESET}")
        for tc in msg.tool_calls:
            _print_tool_call(tc, indent=6)
            _separator("·", 50)

    _separator()


def _view_run(session, run_id: UUID, show_full: bool = False) -> None:
    from db.models import Message, Run, ToolCall

    run = session.query(Run).filter(Run.id == run_id).first()
    if run is None:
        _fail(f"Run not found: {run_id}")
        return

    messages = (
        session.query(Message)
        .filter(Message.run_id == run_id)
        .order_by(Message.sequence_index.asc(), Message.created_at.asc())
        .all()
    )

    # Eagerly attach tool_calls (already loaded via relationship, but ensure ordering)
    from sqlalchemy.orm import subqueryload

    messages = (
        session.query(Message)
        .filter(Message.run_id == run_id)
        .options(subqueryload(Message.tool_calls))
        .order_by(Message.sequence_index.asc(), Message.created_at.asc())
        .all()
    )

    # ── Run summary ──
    _header(f"Run  {run.id}")
    print(f"\n  {'Status:':<14} {_status_str(run.status)}")
    print(f"  {'Trigger:':<14} {YELLOW}{run.trigger_type or '—'}{RESET}")
    print(f"  {'Provider:':<14} {DIM}{run.provider} / {run.model}{RESET}")
    print(f"  {'Started:':<14} {_fmt_dt(run.started_at)}")
    print(f"  {'Ended:':<14} {_fmt_dt(run.ended_at)}")
    print(f"  {'Duration:':<14} {_fmt_duration(run.started_at, run.ended_at)}")
    print(f"  {'Messages:':<14} {CYAN}{len(messages)}{RESET}")

    if not messages:
        _info("\nNo messages for this run.")
        return

    _subheader(f"Messages ({len(messages)})")

    for msg in messages:
        _print_message(msg, show_full=show_full)


# ── Interactive loop ──────────────────────────────────────────────────────────
def _interactive(session, default_limit: int) -> None:
    runs: list = []
    show_full = False

    def _refresh(limit: int) -> None:
        nonlocal runs
        runs = _list_runs(session, limit)

    _refresh(default_limit)

    print(f"\n  {CYAN}Commands:{RESET}")
    print(f"    {BOLD}{'<number>':<14}{RESET} View run by list index")
    print(f"    {BOLD}{'<uuid>':<14}{RESET} View run by full or partial UUID")
    print(f"    {BOLD}{'full / short':<14}{RESET} Toggle full/truncated message content")
    print(f"    {BOLD}{'list [N]':<14}{RESET} Refresh list (optionally show last N runs)")
    print(f"    {BOLD}{'quit':<14}{RESET} Exit")

    while True:
        mode_indicator = f"{GREEN}full{RESET}" if show_full else f"{DIM}short{RESET}"
        try:
            raw = input(f"\n{BOLD}{GREEN}run-viewer [{mode_indicator}{BOLD}{GREEN}]> {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue

        cmd = raw.lower()

        if cmd in ("quit", "exit", "q"):
            break

        if cmd == "full":
            show_full = True
            _ok("Switched to full content mode.")
            continue

        if cmd == "short":
            show_full = False
            _ok("Switched to truncated content mode.")
            continue

        if cmd.startswith("list"):
            parts = cmd.split()
            limit = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else default_limit
            _refresh(limit)
            continue

        # Try index
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(runs):
                _view_run(session, runs[idx].id, show_full=show_full)
            else:
                _fail(f"Index out of range (1–{len(runs)}).")
            continue

        # Try UUID (full or partial prefix match)
        try:
            run_id = UUID(raw)
            _view_run(session, run_id, show_full=show_full)
            continue
        except ValueError:
            pass

        # Partial UUID prefix
        matches = [r for r in runs if str(r.id).startswith(raw)]
        if len(matches) == 1:
            _view_run(session, matches[0].id, show_full=show_full)
        elif len(matches) > 1:
            _fail(f"Ambiguous prefix '{raw}' matches {len(matches)} runs. Be more specific.")
        else:
            _fail(f"Unknown command or UUID: '{raw}'")

    print(f"\n{BOLD}{YELLOW}Goodbye.{RESET}")


# ── Entry point ───────────────────────────────────────────────────────────────
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browse ZETA runs and visualize their messages.")
    parser.add_argument("--run", dest="run_id", type=str, help="Directly open a specific run UUID.")
    parser.add_argument("--limit", dest="limit", type=int, default=30, help="Number of recent runs to list (default: 30).")
    parser.add_argument("--full", dest="full", action="store_true", help="Show full message content (no truncation).")
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    from db.database import init_db

    _info("Connecting to database…")
    try:
        db = init_db()
        _ok("Database ready.")
    except Exception as exc:
        _fail(f"Database init failed: {exc}")
        sys.exit(1)

    with db.get_session() as session:
        if args.run_id:
            try:
                run_id = UUID(args.run_id)
            except ValueError:
                _fail(f"Invalid UUID: {args.run_id}")
                sys.exit(1)
            _view_run(session, run_id, show_full=args.full)
        else:
            _interactive(session, default_limit=args.limit)


if __name__ == "__main__":
    main()
