from tools_utils.init import init

init()

import argparse
import json
from datetime import datetime, time, timezone
from pathlib import Path
from uuid import UUID


from tools_utils.display import header, info, ok, fail
from db.database import init_db
from db.models import MemoryAccessLog, MemoryEntry, Message, Run, ToolCall


# Helpers shared with db_export_runs.py


def _parse_date(value: str, *, is_end: bool) -> datetime:
    """Parse a date or datetime into a timezone-aware UTC datetime."""
    if not value:
        raise ValueError("Empty date value")
    try:
        if len(value) == 10:
            parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
            dt = datetime.combine(parsed_date, time.max if is_end else time.min)
            return dt.replace(tzinfo=timezone.utc)
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(
            f"Invalid date '{value}'. Use YYYY-MM-DD or ISO-8601 (e.g. 2026-02-22T12:00:00Z)."
        ) from exc


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _input_repr(input_payload: dict | None) -> str:
    if input_payload is None:
        return "(no input)"
    try:
        raw = json.dumps(input_payload, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        raw = str(input_payload)
    return _truncate(raw)


# Text renderer

_SEP_RUN = "═" * 80
_SEP_MSG = "" * 60


def _render_run(
    run: Run,
    messages: list[Message],
    tool_calls_by_message: dict[UUID, list[ToolCall]],
    memory_logs_by_message: dict[UUID, list[MemoryAccessLog]],
    memory_by_id: dict[UUID, MemoryEntry],
    run_index: int,
    total: int,
) -> str:
    lines: list[str] = []

    # Run header
    started = _fmt_dt(run.started_at)
    ended = _fmt_dt(run.ended_at)

    if run.started_at and run.ended_at:
        s = (
            run.started_at
            if run.started_at.tzinfo
            else run.started_at.replace(tzinfo=timezone.utc)
        )
        e = (
            run.ended_at
            if run.ended_at.tzinfo
            else run.ended_at.replace(tzinfo=timezone.utc)
        )
        duration = f"{(e - s).total_seconds():.1f}s"
    else:
        duration = "?"

    run_label = f"  RUN {run_index}/{total}  ·  {started} → {ended}  ({duration})  "
    pad = max(0, 80 - len(run_label))
    left_pad = "═" * (pad // 2)
    right_pad = "═" * (pad - pad // 2)
    lines.append(f"{left_pad}{run_label}{right_pad}")

    lines.append(
        f"trigger={run.trigger_type}  provider={run.provider}  model={run.model}  status={run.status}"
    )
    lines.append(f"id={run.id}")

    # Messages
    visible_messages = [m for m in messages if m.role != "tool"]

    if not visible_messages:
        lines.append("")
        lines.append("  (no messages)")
    else:
        for idx, message in enumerate(visible_messages, start=1):
            lines.append("")
            role_label = (message.role or "unknown").upper()
            lines.append(f"[{idx}] {role_label}")
            lines.append(_SEP_MSG)

            # Content
            content = message.content or ""
            if content.strip():
                lines.append(content)
            else:
                lines.append("(empty content)")

            # Tool calls
            tcs = tool_calls_by_message.get(message.id, [])
            if tcs:
                lines.append("")
                for tc in sorted(
                    tcs, key=lambda t: (t.executed_at is None, t.executed_at)
                ):
                    executed = _fmt_dt(tc.executed_at)
                    lines.append(
                        f"  ▸ {tc.tool_name or '(unknown)'}  "
                        f"[executed: {executed}  ·  status: {tc.status or '?'}]"
                    )
                    lines.append(f"    input: {_input_repr(tc.input_payload)}")

            # Memory access logs
            logs = memory_logs_by_message.get(message.id, [])
            if logs:
                lines.append("")
                for log in sorted(
                    logs, key=lambda l: (l.created_at is None, l.created_at)
                ):
                    entry = memory_by_id.get(log.memory_id)
                    title = f'"{entry.title}"' if entry else f"(id={log.memory_id})"
                    access = (log.access_type or "?").upper()
                    reason = log.reason or "(no reason)"
                    lines.append(
                        f"  ◈ MEMORY {access}  ·  {title}  ·  reason: {reason}"
                    )

    lines.append("")
    lines.append(_SEP_RUN)
    return "\n".join(lines)


def export_text(
    from_date: datetime | None,
    to_date: datetime | None,
    last_n: int | None,
    output_path: Path,
) -> Path:
    db = init_db()

    with db.get_session() as session:
        run_query = session.query(Run)
        if from_date is not None:
            run_query = run_query.filter(Run.started_at >= from_date)
        if to_date is not None:
            run_query = run_query.filter(Run.started_at <= to_date)

        if last_n is not None:
            # Fetch last N by date descending, then reverse for chronological display
            run_query = run_query.order_by(Run.started_at.desc(), Run.id.desc()).limit(
                last_n
            )
            runs: list[Run] = list(reversed(run_query.all()))
        else:
            runs = run_query.order_by(Run.started_at.asc(), Run.id.asc()).all()

        run_ids = [r.id for r in runs]

        if run_ids:
            messages: list[Message] = (
                session.query(Message)
                .filter(Message.run_id.in_(run_ids))
                .order_by(
                    Message.run_id.asc(),
                    Message.sequence_index.asc(),
                    Message.created_at.asc(),
                )
                .all()
            )
        else:
            messages = []

        message_ids = [m.id for m in messages]

        if message_ids:
            tool_calls: list[ToolCall] = (
                session.query(ToolCall)
                .filter(ToolCall.message_id.in_(message_ids))
                .order_by(ToolCall.executed_at.asc(), ToolCall.id.asc())
                .all()
            )
            memory_logs: list[MemoryAccessLog] = (
                session.query(MemoryAccessLog)
                .filter(MemoryAccessLog.message_id.in_(message_ids))
                .order_by(MemoryAccessLog.created_at.asc(), MemoryAccessLog.id.asc())
                .all()
            )
        else:
            tool_calls = []
            memory_logs = []

        memory_entries: list[MemoryEntry] = session.query(MemoryEntry).all()

        # Build index structures
        memory_by_id: dict[UUID, MemoryEntry] = {e.id: e for e in memory_entries}

        tool_calls_by_message: dict[UUID, list[ToolCall]] = {}
        for tc in tool_calls:
            tool_calls_by_message.setdefault(tc.message_id, []).append(tc)

        memory_logs_by_message: dict[UUID, list[MemoryAccessLog]] = {}
        for log in memory_logs:
            memory_logs_by_message.setdefault(log.message_id, []).append(log)

        messages_by_run: dict[UUID, list[Message]] = {}
        for msg in messages:
            messages_by_run.setdefault(msg.run_id, []).append(msg)

        # Render
        total = len(runs)
        output_lines: list[str] = []

        output_lines.append(_SEP_RUN)
        output_lines.append(
            f"  ZETA RUNS EXPORT  ·  generated {_fmt_dt(datetime.now(timezone.utc))}"
        )
        filters_info = []
        if from_date:
            filters_info.append(f"from={_fmt_dt(from_date)}")
        if to_date:
            filters_info.append(f"to={_fmt_dt(to_date)}")
        if last_n:
            filters_info.append(f"last={last_n}")
        if filters_info:
            output_lines.append(f"  filters: {',  '.join(filters_info)}")
        output_lines.append(f"  runs: {total}")
        output_lines.append(_SEP_RUN)
        output_lines.append("")

        for i, run in enumerate(runs, start=1):
            run_messages = messages_by_run.get(run.id, [])
            block = _render_run(
                run=run,
                messages=run_messages,
                tool_calls_by_message=tool_calls_by_message,
                memory_logs_by_message=memory_logs_by_message,
                memory_by_id=memory_by_id,
                run_index=i,
                total=total,
            )
            output_lines.append(block)
            output_lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    return output_path


# CLI


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export ZETA runs into a human-readable text file."
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        type=str,
        help="Start date (UTC): YYYY-MM-DD or ISO-8601",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        type=str,
        help="End date (UTC): YYYY-MM-DD or ISO-8601",
    )
    parser.add_argument(
        "--last",
        dest="last_n",
        type=int,
        help="Export only the N most recent runs (chronological order in output)",
    )
    parser.add_argument(
        "--output",
        dest="output",
        type=str,
        help="Output .txt path. Default: <cwd>/exports/runs_export_<timestamp>.txt",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    from_date = _parse_date(args.from_date, is_end=False) if args.from_date else None
    to_date = _parse_date(args.to_date, is_end=True) if args.to_date else None

    if from_date and to_date and from_date > to_date:
        parser.error("--from must be <= --to")

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = Path.cwd() / "exports" / f"runs_export_{timestamp}.txt"

    header("ZETA — Runs Text Export")
    info(f"Output: {output_path}")
    if args.last_n:
        info(f"Mode: last {args.last_n} runs")
    elif from_date or to_date:
        info(f"Mode: filtered  from={from_date}  to={to_date}")
    else:
        info("Mode: full export")

    try:
        exported = export_text(
            from_date=from_date,
            to_date=to_date,
            last_n=args.last_n,
            output_path=output_path,
        )
        ok(f"\nExport complete: {exported}")
    except Exception as exc:
        fail(f"\nExport failed: {exc}")
        raise


if __name__ == "__main__":
    main()
