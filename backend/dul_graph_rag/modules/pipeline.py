"""The public entry point: text in, gated DUL triples in FalkorDB.

This is the one function a human normally calls. It ties together the whole
pipeline without exposing any of its stages::

    from notebooks.modules.pipeline import ingest

    report = ingest("Ada Lovelace worked on the Analytical Engine with
                     Charles Babbage in London.")

    print(report.created, "triples written;", report.rejected, "rejected")

The mapping is *not* optional and cannot be skipped: `map_text()` runs the LLM
extraction, the Jev ontology mapping and the strict DUL gate, and only the
triples that survive the gate are ever handed to a writer. Nothing in this
module (or below it) hardcodes a host, a graph name, a model id or a
vocabulary term -- all of it comes from `.env`, `graph.json` and
`data/*.json`.
"""

from __future__ import annotations

from typing import Any

from .crud import manual_bulk_create
from .deps import get_jev_deps
from .extraction import ExtractionResult, IngestReport
from .facade import default_group
from .mapping import map_text
from .settings import S, Settings, get_settings


async def ingest(
    text: str,
    client: Any = None,
    graphiti: Any = None,
    deps: dict[str, Any] | None = None,
    settings: Settings | None = None,
    group: str | None = None,
    *,
    session: Any = None,
) -> IngestReport:
    """Map `text` onto DUL and write the triples that pass the strict gate.

    Parameters
    ----------
    text:
        The chunk to extract entities and relations from.
    client:
        An open `JevClient`. Required unless `session` is given.
    graphiti:
        A Graphiti instance. Required unless `session` is given.
    deps:
        The gate dependencies (schema / ancestors / lineage / edge_map).
        Built on first use and cached process-wide.
    group:
        Logical partition to write into. Defaults to the configured group.
    session:
        An open `OntologySession`; supplies `client`, `graphiti`, `deps` and
        `group` so a caller does not have to unpack them.
    """

    s = settings or get_settings()
    if session is not None:
        session.require_open()
        client = client or session.jev
        graphiti = graphiti or session.graphiti
        deps = deps or session.deps
        group = group or session.group
    if client is None:
        raise ValueError("pass either an open `JevClient` or an open `OntologySession`")
    if graphiti is None:
        raise ValueError("pass either a `graphiti` instance or an open `OntologySession`")

    # Resolve the gate dependencies once, here. `map_text()` would happily
    # build its own copy when given `None`, but the writer needs the very same
    # snapshot -- passing `None` through would let the gate and the writer
    # disagree about the vocabulary.
    gate_deps = deps or get_jev_deps()
    mapping = await map_text(text, client, gate_deps, settings=s)

    valid = [item.triple.model_dump() for item in mapping.triples if item.gate_ok]
    rejected = [
        f"{item.pair_key}: {'; '.join(item.gate_issues)}"
        for item in mapping.triples
        if not item.gate_ok
    ]

    report = await manual_bulk_create(
        graphiti, gate_deps, valid, group=group or default_group(s)
    )
    return IngestReport(
        text=text,
        mapping=mapping,
        created=report.created,
        rejected=report.rejected + len(rejected),
        rejected_details=[*rejected, *report.rejected_details],
        vector_status=report.vector_status,
        warnings=report.warnings,
        usage=client.usage.model_copy(),
    )


async def plan(
    text: str,
    client: Any = None,
    deps: dict[str, Any] | None = None,
    settings: Settings | None = None,
    *,
    session: Any = None,
) -> Any:
    """Map `text` onto DUL **without writing anything**.

    Useful to inspect what the pipeline believes before committing it to the
    graph -- the whole map is gate-scored, so `mapping.triples[i].gate_ok`
    tells you exactly which rows a subsequent `ingest()` would persist.
    """

    s = settings or get_settings()
    if session is not None:
        session.require_open()
        client = client or session.jev
        deps = deps or session.deps
    if client is None:
        raise ValueError("pass either an open `JevClient` or an open `OntologySession`")
    return await map_text(text, client, deps or get_jev_deps(), settings=s)


def ingest_blocking(text: str, **kwargs: Any) -> IngestReport:
    """Synchronous wrapper around `ingest()` for a plain script or a cell.

    Opens a session when none is supplied, so a single call is enough::

        from notebooks.modules.pipeline import ingest_blocking
        report = ingest_blocking("some text")
    """

    import asyncio

    from .session import OntologySession

    async def _run() -> IngestReport:
        if kwargs.get("session") is not None:
            return await ingest(text, **kwargs)
        async with OntologySession() as session:
            return await ingest(text, session=session, **kwargs)

    return asyncio.run(_run())


__all__ = ["IngestReport", "ExtractionResult", "ingest", "ingest_blocking", "plan", "S"]
