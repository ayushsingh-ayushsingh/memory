"""TOON encoding with human-readable dates.

The conductor agent consumes tool output and retrieved context. JSON is fine to
produce, but before it reaches the model we (1) rewrite every ISO-8601 date into
a natural format like ``October 24, 2026 at 1:01:13 PM UTC`` and (2) encode the
result as TOON (Token-Oriented Object Notation) to cut token usage on the Groq
free plan.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from toon import encode as _toon_encode

# ISO-8601 date/time, with optional fractional seconds, offset or Z suffix.
_ISO_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)


def natural_time(dt: datetime | None = None) -> str:
    """Format a datetime as ``October 24, 2026 at 1:01:13 PM UTC`` (local tz).

    Matches the exact format required by the prompt-preprocessing spec. A naive
    datetime is assumed to already be local; an aware one is converted to local.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone()  # convert to the host's local timezone
    hour = local.strftime("%I").lstrip("0") or "0"
    return (
        f"{local.strftime('%B')} {local.day}, {local.year} "
        f"at {hour}:{local.strftime('%M:%S %p')} {local.tzname() or 'UTC'}"
    )


def _natural_date_str(value: str) -> str:
    """Rewrite a single ISO date substring into natural format."""
    try:
        # Handle trailing Z so fromisoformat accepts it on 3.11+.
        iso = value.replace("Z", "+00:00") if value.endswith("Z") else value
        dt = datetime.fromisoformat(iso)
    except ValueError:
        try:
            d = date.fromisoformat(value)
        except ValueError:
            return value
        return f"{d.strftime('%B')} {d.day}, {d.year}"
    return natural_time(dt)


def naturalize_dates(value: Any) -> Any:
    """Recursively convert ISO-8601 date strings to natural format.

    Leaves every other value untouched. Datetime objects become natural strings
    too. This runs *before* TOON encoding so the model reads readable dates.
    """
    if isinstance(value, datetime):
        return natural_time(value)
    if isinstance(value, date):
        return f"{value.strftime('%B')} {value.day}, {value.year}"
    if isinstance(value, str):
        if _ISO_RE.fullmatch(value.strip()):
            return _natural_date_str(value.strip())
        return value
    if isinstance(value, dict):
        return {k: naturalize_dates(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [naturalize_dates(v) for v in value]
    return value


def toon(value: Any, *, naturalize: bool = True) -> str:
    """Encode a JSON-able value to TOON, naturalizing dates first.

    Returns a TOON string ready to hand to the conductor agent. Falls back to a
    readable string if the value can't be encoded.
    """
    prepared = naturalize_dates(value) if naturalize else value
    try:
        return _toon_encode(prepared)
    except Exception:  # noqa: BLE001 — never fail the caller over encoding
        return str(prepared)


__all__ = ["natural_time", "naturalize_dates", "toon"]
