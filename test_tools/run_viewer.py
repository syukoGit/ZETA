from tools_utils.init import init

init()

import argparse
import sys
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import subqueryload

from db.db_tools import DBTools
from db.models import Message, Run
from db.database import DatabaseManager
from test_tools.tools_utils.check_connections import init_database
from test_tools.tools_utils.display import *
from utils.json_utils import dumps_json

# Formatting helpers
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
    return f"{colour}{status or '?'}"


def _role_str(role: str | None) -> str:
    colour = _ROLE_COLOUR.get(role or "", DIM)
    return f"{BOLD}{colour}{(role or '?').upper():<12}"


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return f"{DIM}—"
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


# Run listing
def _print_run_row(index: int, run, msg_count: int) -> None:
    idx_str = f"{BOLD}{index:>3}.{RESET}"
    short = f"{DIM}{_short_id(run.id)}…{RESET}"
    status = _status_str(run.status)
    started = _fmt_dt(run.started_at)
    duration = _fmt_duration(run.started_at, run.ended_at)
    msgs = f"{CYAN}{msg_count} msg{'s' if msg_count != 1 else ''}{RESET}"
    model_info = f"{DIM}{run.provider}/{run.model}{RESET}"
    trigger = f"{YELLOW}{run.trigger_type or '?'}{RESET}"

    message(
        f"  {idx_str} [{short}]  {status:<30}  {trigger:<20}  {started}  {duration:>8}  {msgs}  {model_info}"
    )


def _list_runs(session, limit: int) -> list:
    runs = session.query(Run).order_by(Run.started_at.desc()).limit(limit).all()

    counts_q = (
        session.query(Message.run_id, func.count(Message.id).label("cnt"))
        .filter(Message.run_id.in_([r.id for r in runs]))
        .group_by(Message.run_id)
        .all()
    )
    count_map = {row.run_id: row.cnt for row in counts_q}

    header(f"Runs  (newest {limit} shown)")
    message(
        f"\n  {BOLD}{'#':>4}  {'ID':9}  {'Status':<20}  "
        f"{'Trigger':<20}  {'Started (UTC)':>23}  {'Dur':>8}  {'Msgs'}"
    )
    separator("─", 100)

    for i, run in enumerate(runs):
        _print_run_row(i + 1, run, count_map.get(run.id, 0))

    return runs


# ── Message display ───────────────────────────────────────────────────────────
def _print_tool_call(tc, indent: int = 8) -> None:
    pad = " " * indent
    status_colour = (
        GREEN if tc.status == "completed" else RED if tc.status == "failed" else CYAN
    )
    message(
        f"{pad}{BOLD}{MAGENTA}⚙  {tc.tool_name}{RESET}  "
        f"{status_colour}[{tc.status or '?'}]{RESET}  "
        f"{DIM}{_fmt_dt(tc.executed_at)}"
    )
    message(f"{pad}{DIM}id: {tc.id}")

    if tc.input_payload:
        try:
            payload_str = dumps_json(tc.input_payload, indent=2)
        except Exception:
            payload_str = str(tc.input_payload)
        message(f"{pad}{DIM}input:")
        for line in payload_str.splitlines():
            message(f"{pad}  {DIM}{line}")

    if tc.output_payload:
        try:
            out_str = dumps_json(tc.output_payload, indent=2)
        except Exception:
            out_str = str(tc.output_payload)
        message(f"{pad}{DIM}output:")
        for line in out_str.splitlines():
            message(f"{pad}  {DIM}{line}")


def _print_message(msg, show_full: bool = False) -> None:
    role_str = _role_str(msg.role)
    seq = f"{DIM}#{msg.sequence_index}{RESET}" if msg.sequence_index is not None else ""
    ts = f"{DIM}{_fmt_dt(msg.created_at)}{RESET}"
    id_str = f"{DIM}id: {msg.id}{RESET}"

    message(f"\n  {role_str}  {seq}  {ts}")
    message(f"    {id_str}")

    content = msg.content or ""
    if content:
        max_chars = None if show_full else 800
        display = (
            content
            if (max_chars is None or len(content) <= max_chars)
            else content[:max_chars]
            + f"\n{DIM}… ({len(content) - max_chars} more chars — use 'full' mode to expand){RESET}"
        )
        for line in display.splitlines():
            message(f"      {line}")

    if msg.tool_calls:
        message(f"\n    {BOLD}{MAGENTA}Tool calls ({len(msg.tool_calls)}):{RESET}")
        for tc in msg.tool_calls:
            _print_tool_call(tc, indent=6)
            separator("·", 50)

    separator()


def _view_run(session, run_id: UUID, show_full: bool = False) -> None:
    run = session.query(Run).filter(Run.id == run_id).first()
    if run is None:
        fail(f"Run not found: {run_id}")
        return

    messages = (
        session.query(Message)
        .filter(Message.run_id == run_id)
        .order_by(Message.sequence_index.asc(), Message.created_at.asc())
        .all()
    )

    messages = (
        session.query(Message)
        .filter(Message.run_id == run_id)
        .options(subqueryload(Message.tool_calls))
        .order_by(Message.sequence_index.asc(), Message.created_at.asc())
        .all()
    )

    # Run summary
    header(f"Run  {run.id}")
    message(f"\n  {'Status:':<14} {_status_str(run.status)}")
    message(f"  {'Trigger:':<14} {YELLOW}{run.trigger_type or '—'}")
    message(f"  {'Provider:':<14} {DIM}{run.provider} / {run.model}")
    message(f"  {'Started:':<14} {_fmt_dt(run.started_at)}")
    message(f"  {'Ended:':<14} {_fmt_dt(run.ended_at)}")
    message(f"  {'Duration:':<14} {_fmt_duration(run.started_at, run.ended_at)}")
    message(f"  {'Messages:':<14} {CYAN}{len(messages)}")

    if not messages:
        info("\nNo messages for this run.")
        return

    subheader(f"Messages ({len(messages)})")

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

    info(f"\n  Commands:")
    message(f"    {BOLD}{'<number>':<14}{RESET} View run by list index")
    message(f"    {BOLD}{'<uuid>':<14}{RESET} View run by full or partial UUID")
    message(
        f"    {BOLD}{'full / short':<14}{RESET} Toggle full/truncated message content"
    )
    message(
        f"    {BOLD}{'list [N]':<14}{RESET} Refresh list (optionally show last N runs)"
    )
    message(f"    {BOLD}{'quit':<14}{RESET} Exit")

    while True:
        mode_indicator = f"{GREEN}full{RESET}" if show_full else f"{DIM}short{RESET}"
        try:
            raw = prompt(
                f"\n{BOLD}{GREEN}run-viewer [{mode_indicator}{BOLD}{GREEN}]> {RESET}"
            )
        except (EOFError, KeyboardInterrupt):
            break

        if not raw:
            continue

        cmd = raw.lower()

        if cmd in ("quit", "exit", "q"):
            break

        if cmd == "full":
            show_full = True
            ok("Switched to full content mode.")
            continue

        if cmd == "short":
            show_full = False
            ok("Switched to truncated content mode.")
            continue

        if cmd.startswith("list"):
            parts = cmd.split()
            limit = (
                int(parts[1])
                if len(parts) > 1 and parts[1].isdigit()
                else default_limit
            )
            _refresh(limit)
            continue

        # Try index
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(runs):
                _view_run(session, runs[idx].id, show_full=show_full)
            else:
                fail(f"Index out of range (1–{len(runs)}).")
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
            fail(
                f"Ambiguous prefix '{raw}' matches {len(matches)} runs. Be more specific."
            )
        else:
            fail(f"Unknown command or UUID: '{raw}'")

    message(f"\n{BOLD}{YELLOW}Goodbye.")


# Entry point
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Browse ZETA runs and visualize their messages."
    )
    parser.add_argument(
        "--run", dest="run_id", type=str, help="Directly open a specific run UUID."
    )
    parser.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=30,
        help="Number of recent runs to list (default: 30).",
    )
    parser.add_argument(
        "--full",
        dest="full",
        action="store_true",
        help="Show full message content (no truncation).",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    db: DatabaseManager
    db, run_id, _ = init_database("run_viewer")

    try:
        with db.get_session() as session:
            if args.run_id:
                try:
                    view_run_id = UUID(args.run_id)
                except ValueError:
                    fail(f"Invalid UUID: {args.run_id}")
                    sys.exit(1)
                _view_run(session, view_run_id, show_full=args.full)
            else:
                _interactive(session, default_limit=args.limit)
    finally:
        db_tools = DBTools()
        if run_id is not None:
            db_tools.end_run(run_id)


if __name__ == "__main__":
    main()
