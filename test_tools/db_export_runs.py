"""
Export ZETA PostgreSQL data into a structured JSON file for run analysis.

Usage examples:
    python test_tools/db_export_runs.py
    python test_tools/db_export_runs.py --from 2026-01-01 --to 2026-02-22
    python test_tools/db_export_runs.py --from 2026-02-01T00:00:00Z --output my_export.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import inspect

# Ensure the project root and script/ are on sys.path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "script"))

from dotenv import load_dotenv

load_dotenv(os.path.join(_root, ".env"))

from db.database import init_db
from db.models import MemoryAccessLog, MemoryEntry, Message, Run, ToolCall


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


def _serialize(value: Any) -> Any:
    """Serialize values to JSON-safe representations."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(val) for key, val in value.items()}
    if hasattr(value, "tolist"):
        return _serialize(value.tolist())
    return str(value)


def _row_to_dict(instance: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy model instance into a JSON-serializable dict."""
    mapper = inspect(instance.__class__)
    payload: dict[str, Any] = {}
    for column in mapper.columns:
        payload[column.key] = _serialize(getattr(instance, column.key))
    return payload


def _build_run_analysis(
    runs: list[Run],
    messages: list[Message],
    tool_calls: list[ToolCall],
    memory_logs: list[MemoryAccessLog],
    memory_entries: list[MemoryEntry],
) -> list[dict[str, Any]]:
    """Build a denormalized run-centric structure for analysis."""
    memory_by_id = {entry.id: entry for entry in memory_entries}

    tool_calls_by_message: dict[UUID, list[ToolCall]] = {}
    for item in tool_calls:
        tool_calls_by_message.setdefault(item.message_id, []).append(item)

    memory_logs_by_message: dict[UUID, list[MemoryAccessLog]] = {}
    for item in memory_logs:
        memory_logs_by_message.setdefault(item.message_id, []).append(item)

    messages_by_run: dict[UUID, list[Message]] = {}
    for item in messages:
        messages_by_run.setdefault(item.run_id, []).append(item)

    runs_analysis: list[dict[str, Any]] = []

    for run in runs:
        run_messages = sorted(
            messages_by_run.get(run.id, []),
            key=lambda msg: ((msg.sequence_index is None), msg.sequence_index if msg.sequence_index is not None else 10**9),
        )

        message_entries: list[dict[str, Any]] = []
        for message in run_messages:
            linked_tool_calls = [_row_to_dict(tc) for tc in tool_calls_by_message.get(message.id, [])]

            linked_memory_events: list[dict[str, Any]] = []
            for event in memory_logs_by_message.get(message.id, []):
                event_payload = _row_to_dict(event)
                memory_entry = memory_by_id.get(event.memory_id)
                event_payload["memory_entry"] = _row_to_dict(memory_entry) if memory_entry else None
                linked_memory_events.append(event_payload)

            message_payload = _row_to_dict(message)
            message_payload["tool_calls"] = linked_tool_calls
            message_payload["memory_access_events"] = linked_memory_events
            message_entries.append(message_payload)

        run_payload = _row_to_dict(run)
        run_payload["messages"] = message_entries
        run_payload["counts"] = {
            "messages": len(message_entries),
            "tool_calls": sum(len(item["tool_calls"]) for item in message_entries),
            "memory_access_events": sum(len(item["memory_access_events"]) for item in message_entries),
        }

        runs_analysis.append(run_payload)

    return runs_analysis


def export_database(from_date: datetime | None, to_date: datetime | None, output_path: Path) -> Path:
    """Export DB content and run-centric analysis into a single JSON file."""
    db = init_db()

    with db.get_session() as session:
        run_query = session.query(Run)
        if from_date is not None:
            run_query = run_query.filter(Run.started_at >= from_date)
        if to_date is not None:
            run_query = run_query.filter(Run.started_at <= to_date)

        runs: list[Run] = run_query.order_by(Run.started_at.asc(), Run.id.asc()).all()
        run_ids = [item.id for item in runs]

        if run_ids:
            messages: list[Message] = (
                session.query(Message)
                .filter(Message.run_id.in_(run_ids))
                .order_by(Message.run_id.asc(), Message.sequence_index.asc(), Message.created_at.asc())
                .all()
            )
        else:
            messages = []

        message_ids = [item.id for item in messages]

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

        memory_entries: list[MemoryEntry] = session.query(MemoryEntry).order_by(MemoryEntry.created_at.asc(), MemoryEntry.id.asc()).all()

        payload = {
            "metadata": {
                "exported_at_utc": datetime.now(timezone.utc).isoformat(),
                "database_url_present": bool(os.getenv("DATABASE_URL")),
                "filters": {
                    "from": _serialize(from_date),
                    "to": _serialize(to_date),
                },
                "counts": {
                    "runs": len(runs),
                    "messages": len(messages),
                    "tool_calls": len(tool_calls),
                    "memory_access_log": len(memory_logs),
                    "memory_entries": len(memory_entries),
                },
                "notes": [
                    "Run-linked tables are filtered by run.started_at when --from/--to is used.",
                    "memory_entries are exported in full for complete DB context.",
                ],
            },
            "tables_raw": {
                "runs": [_row_to_dict(item) for item in runs],
                "messages": [_row_to_dict(item) for item in messages],
                "tool_calls": [_row_to_dict(item) for item in tool_calls],
                "memory_access_log": [_row_to_dict(item) for item in memory_logs],
                "memory_entries": [_row_to_dict(item) for item in memory_entries],
            },
            "runs_analysis": _build_run_analysis(
                runs=runs,
                messages=messages,
                tool_calls=tool_calls,
                memory_logs=memory_logs,
                memory_entries=memory_entries,
            ),
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)

    return output_path


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export ZETA DB into a JSON file for run analysis.")
    parser.add_argument("--from", dest="from_date", type=str, help="Start date (UTC): YYYY-MM-DD or ISO-8601")
    parser.add_argument("--to", dest="to_date", type=str, help="End date (UTC): YYYY-MM-DD or ISO-8601")
    parser.add_argument(
        "--output",
        dest="output",
        type=str,
        help="Output JSON path. Default: test_tools/exports/runs_export_<timestamp>.json",
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
        output_path = Path(_root) / "test_tools" / "exports" / f"runs_export_{timestamp}.json"

    exported_file = export_database(from_date=from_date, to_date=to_date, output_path=output_path)
    print(f"Export complete: {exported_file}")


if __name__ == "__main__":
    main()
