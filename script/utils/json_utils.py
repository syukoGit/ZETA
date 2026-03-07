from datetime import datetime
from decimal import Decimal
import json
import math
from typing import Any, Mapping
from uuid import UUID


FLOAT_ROUND_DIGITS = 4


def _to_json_key(key: Any) -> str:
    """Convert mapping keys to JSON-safe string representation."""
    if isinstance(key, str):
        return key
    if isinstance(key, UUID):
        return str(key)
    if isinstance(key, datetime):
        return key.isoformat()
    return str(key)


def to_json_compatible(value: Any) -> Any:
    """Recursively normalize a value to JSON-compatible primitives.

    Unknown non-serializable objects are converted to str(value).
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return round(value, FLOAT_ROUND_DIGITS) if math.isfinite(value) else None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {
            _to_json_key(key): to_json_compatible(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_json_compatible(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def dumps_json(value: Any, **kwargs: Any) -> str:
    """Serialize using project JSON rules for DB JSON/JSONB columns."""
    options = {"ensure_ascii": False, "allow_nan": False}
    options.update(kwargs)
    return json.dumps(to_json_compatible(value), **options)