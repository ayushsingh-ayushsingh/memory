from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, field_validator

SEARCH_URL = "http://localhost:8001/search"
DEFAULT_LIMIT = 5
MAX_LIMIT = 100

# Groq's on-demand tier for the reasoning model has a very small token rate
# limit (~8k tokens/min). Every search result is echoed back into the model's
# context on each subsequent tool round, so oversized result blobs quickly
# blow the budget and trigger 429s (which the SDK then retries with multi-second
# backoffs — the request looks like it hangs). Keep each result lean: the model
# only needs the headline figure, not the whole paragraph.
MAX_CONTENT_CHARS = 400


def _truncate(text: str) -> str:
    if len(text) <= MAX_CONTENT_CHARS:
        return text
    return text[: MAX_CONTENT_CHARS - 1].rstrip() + "…"


class SearchError(Exception):
    """Raised when the search service is unreachable or returns an invalid response."""


class SearchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = ""
    title: str = ""
    content: str = ""

    @field_validator("url", "title", "content", mode="before")
    @classmethod
    def normalize(cls, value: Any) -> str:
        if value is None:
            return ""
        text = value.strip() if isinstance(value, str) else str(value)
        # Titles and content are echoed into the model's context; cap them so a
        # handful of searches can't exhaust Groq's small token-rate window.
        return _truncate(text)


def search_tool(query: str, number: int = DEFAULT_LIMIT) -> list[dict[str, str]]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    if isinstance(number, bool) or not isinstance(number, int):
        raise TypeError("number must be an integer")

    if not 1 <= number <= MAX_LIMIT:
        raise ValueError(f"number must be between 1 and {MAX_LIMIT}")

    timeout = httpx.Timeout(
        connect=2.0,
        read=10.0,
        write=5.0,
        pool=2.0,
    )

    try:
        response = httpx.get(
            SEARCH_URL,
            params={"q": query.strip(), "format": "json"},
            timeout=timeout,
        )
        _ = response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SearchError(f"search service request failed: {exc}") from exc

    data = response.json()

    raw_results = data.get("results", []) if isinstance(data, dict) else []
    if not isinstance(raw_results, list):
        return []

    results = [
        SearchItem.model_validate(
            {
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "content": item.get("content", ""),
            }
        )
        for item in raw_results[:number]
        if isinstance(item, dict)
    ]

    return [item.model_dump() for item in results]
