from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import (
    BaseModel,
)



# %% Cell 03 — NOTEBOOK RUNTIME: one event loop, plus printers
#
# A marimo notebook keeps one event loop alive across cells; so does this
# one. `run()` executes one async stage on that loop and returns its result,
# which lets every cell below read like straight-line notebook code while the
# FalkorDB/Qdrant/TypeSafe connections stay bound to a single loop.

LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


def run(coro: Any) -> Any:
    """Execute one async stage on the notebook's persistent event loop."""
    return LOOP.run_until_complete(coro)


# %% Printers — the marimo markdown/table replacements, as plain functions


def section(title: str) -> None:
    """Banner for one notebook cell, so the output reads top-to-bottom."""
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _plain(value: Any) -> str:
    """One cell of a printed table: str(), newlines collapsed."""
    text = "" if value is None else str(value)
    return " ".join(text.split())


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def table(rows: list[dict[str, Any]], title: str = "", max_col_width: int = 52) -> None:
    """Print a list of dicts as an aligned table (the mo.ui.table stand-in)."""
    if title:
        print(f"\n-- {title}")
    if not rows:
        print("   (no rows)")
        return
    cols: list[str] = []
    for row in rows:
        for key in row:
            if key not in cols:
                cols.append(key)
    widths = {
        col: min(
            max([len(col)] + [len(_plain(row.get(col))) for row in rows]),
            max_col_width,
        )
        for col in cols
    }
    print("   " + " | ".join(_clip(col, widths[col]).ljust(widths[col]) for col in cols))
    print("   " + "-+-".join("-" * widths[col] for col in cols))
    for row in rows:
        print(
            "   "
            + " | ".join(
                _clip(_plain(row.get(col)), widths[col]).ljust(widths[col])
                for col in cols
            )
        )


def bullets(items: list[Any], title: str = "") -> None:
    """Print a list of scalars on one wrapped line (the mo.md list stand-in)."""
    label = f"{title}: " if title else ""
    print(f"   {label}{', '.join(str(i) for i in items) if items else '—'}")


def show(report: Any) -> None:
    """Print any pydantic report / dict as JSON (the mo.json stand-in)."""
    if isinstance(report, BaseModel):
        payload = report.model_dump()
    elif isinstance(report, dict):
        payload = report
    else:
        payload = {"value": report}
    print(json.dumps(payload, indent=2, default=str))
