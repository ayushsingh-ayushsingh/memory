from __future__ import annotations

from typing import Any

from .crud import (
    manual_bulk_create,
    manual_bulk_delete,
    manual_create_triple,
    manual_delete_triple,
    manual_reset_group,
    manual_search,
    manual_stats,
    manual_sync_vectors,
    manual_update_triple,
)
from .reports import (
    BulkDeleteReport,
    BulkReport,
    CreateReport,
    DeleteReport,
    SearchReport,
)
from .settings import Settings, get_settings


# %% Cell 19b — jev_crud facade: group-aware wrappers over the CRUD writer
#
# `tools/jev_crud.py` in the original project is a thin facade that binds the
# manual CRUD functions to the `jev_group` partition. It is inlined here too so
# the pipeline's `ingest_text()` (Cell 18) can call `bulk_create()` directly.


def default_group(settings: Settings | None = None) -> str:
    """Logical partition used by the Jev pipeline (settings-driven)."""
    return (settings or get_settings()).jev_group


async def create(
    graphiti: Any,
    deps: dict[str, Any],
    triple: dict[str, Any],
    group: str | None = None,
) -> CreateReport:
    """Gate one triple; write it LLM-free. Never writes unvalidated data."""
    return await manual_create_triple(
        graphiti, deps, triple, group=group or default_group()
    )


async def bulk_create(
    graphiti: Any,
    deps: dict[str, Any],
    triples: list[dict[str, Any]],
    group: str | None = None,
) -> BulkReport:
    """Gate every triple; write the valid subset LLM-free (no episodes)."""
    return await manual_bulk_create(
        graphiti, deps, triples, group=group or default_group()
    )


async def update(
    graphiti: Any,
    deps: dict[str, Any],
    triple: dict[str, Any],
    group: str | None = None,
) -> CreateReport:
    """Update = gate + delete the old edge + write the new version."""
    return await manual_update_triple(
        graphiti, deps, triple, group=group or default_group()
    )


async def delete(
    graphiti: Any, fact_key: str, group: str | None = None
) -> DeleteReport:
    """Delete one edge (by fact key) from FalkorDB and its Qdrant vector."""
    return await manual_delete_triple(graphiti, fact_key, group=group or default_group())


async def bulk_delete(
    graphiti: Any, fact_keys: list[str], group: str | None = None
) -> BulkDeleteReport:
    """Delete many edges by fact key; report per-key outcomes."""
    return await manual_bulk_delete(graphiti, fact_keys, group=group or default_group())


async def search(
    graphiti: Any,
    deps: dict[str, Any],
    query: str,
    limit: int | None = None,
    group: str | None = None,
) -> SearchReport:
    """Graph fulltext + Qdrant vectors, fused and reranked by the jina model."""
    return await manual_search(
        graphiti, deps, query, limit=limit, group=group or default_group()
    )


async def stats(graphiti: Any, group: str | None = None) -> dict[str, Any]:
    """Entity/edge counts + sample + mirror status for the Jev partition."""
    return await manual_stats(graphiti, group=group or default_group())


async def reset(graphiti: Any, group: str | None = None) -> dict[str, Any]:
    """Wipe the Jev partition (FalkorDB nodes + Qdrant points)."""
    return await manual_reset_group(graphiti, group=group or default_group())


async def sync_vectors(graphiti: Any, group: str | None = None) -> dict[str, Any]:
    """Replay the vector mirror for facts that missed it during an outage."""
    return await manual_sync_vectors(graphiti, group=group or default_group())
