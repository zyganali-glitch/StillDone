"""Deterministic canonical serialization contract for StillDone.

Provides stable, reproducible JSON-compatible primitive projection and serialization
for cryptographic hashing and content addressing.
Rejects non-canonical and unsupported types fail-closed.
"""

from __future__ import annotations

import dataclasses
import json
import math
import unicodedata
import uuid
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any


def normalize_datetime(dt: datetime) -> str:
    """Normalize a timezone-aware datetime to a canonical UTC ISO-8601 string.

    Fails closed if the datetime is naive (missing timezone).
    """
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"Naive datetime is not permitted; must be timezone-aware: {dt!r}")
    utc_dt = dt.astimezone(UTC)
    return utc_dt.isoformat()


def to_canonical_primitive(obj: Any) -> Any:
    """Recursively convert an object into JSON-compatible canonical primitives.

    Guarantees:
    - Dict keys are strings and sorted lexicographically.
    - Strings are NFC-normalized Unicode.
    - Datetimes are normalized to UTC ISO-8601 strings.
    - Dates are converted to ISO format (YYYY-MM-DD).
    - Enums are projected to their canonical values.
    - Single-value ID wrapper dataclasses and UUIDs are projected to their string values.
    - Dataclasses are projected to dicts with sorted field names.
    - Objects with `to_canonical()` or `to_dict()` methods are projected via those methods.
    - Non-finite floats (NaN, Inf, -Inf) raise ValueError.
    - Unsupported types raise TypeError fail-closed.
    """
    # Enums must be checked before str/int because StrEnum is a str and IntEnum is an int
    if isinstance(obj, Enum):
        return to_canonical_primitive(obj.value)

    # 1. Primitives: None, bool, int, float, str
    if obj is None:
        return None

    # bool must be checked before int because isinstance(True, int) is True in Python
    if isinstance(obj, bool):
        return obj

    if isinstance(obj, int):
        return obj

    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(
                f"Non-finite float is not permitted in canonical serialization: {obj!r}"
            )
        # Normalize negative zero to zero
        return 0.0 if obj == 0.0 else obj

    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)

    # 2. Datetime / Date
    if isinstance(obj, datetime):
        return normalize_datetime(obj)

    if isinstance(obj, date):
        return obj.isoformat()

    # 3. UUID
    if isinstance(obj, uuid.UUID):
        return str(obj)

    # 4. Explicit canonical projection hooks
    if hasattr(obj, "to_canonical") and callable(obj.to_canonical):
        return to_canonical_primitive(obj.to_canonical())

    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return to_canonical_primitive(obj.to_dict())

    # 5. ID wrapper dataclasses (frozen single-field 'value: str' wrappers)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        fields = dataclasses.fields(obj)
        if len(fields) == 1 and fields[0].name == "value":
            val = getattr(obj, "value", None)
            if isinstance(val, str):
                return val
        # General dataclass: project all fields to a sorted dictionary
        return {
            f.name: to_canonical_primitive(getattr(obj, f.name))
            for f in sorted(fields, key=lambda f: f.name)
        }

    # 6. Dictionaries
    if isinstance(obj, dict):
        projected_dict: dict[str, Any] = {}
        for k, v in sorted(obj.items(), key=lambda item: str(item[0])):
            if not isinstance(k, str):
                msg = (
                    "Dictionary keys must be strings for canonical serialization, "
                    f"got {type(k).__name__}: {k!r}"
                )
                raise TypeError(msg)
            norm_key = unicodedata.normalize("NFC", k)
            projected_dict[norm_key] = to_canonical_primitive(v)
        return projected_dict

    # 8. Sequences (lists, tuples)
    if isinstance(obj, (list, tuple)):
        return [to_canonical_primitive(item) for item in obj]

    # 9. Fail-closed for all unsupported types (e.g. set, custom objects, callables, etc.)
    raise TypeError(f"Unsupported type for canonical serialization: {type(obj).__name__} ({obj!r})")


def canonical_json(obj: Any) -> str:
    """Serialize an object into a deterministic canonical JSON string.

    Uses sorted keys, no extraneous whitespace separators, ensure_ascii=False,
    and allow_nan=False.
    """
    primitive = to_canonical_primitive(obj)
    return json.dumps(
        primitive,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_serialize(obj: Any) -> bytes:
    """Serialize an object into deterministic canonical UTF-8 bytes for hashing."""
    return canonical_json(obj).encode("utf-8")
