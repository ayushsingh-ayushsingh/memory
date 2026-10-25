from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .chunk_store import ChunkRecord, get_chunk_store
from .chunking import prepare_text
from .crud import manual_bulk_create
from .deps import get_jev_deps
from .extraction import MappingResult
from .mapping import map_text
from .reports import triple_key_of
from .settings import Settings, get_settings


# %% Long-context extract pipeline
#
# One long text -> (coref resolve) -> (disjoint chunks) -> (chunk vectors in
# Qdrant) -> (concurrent per-chunk LLM extract + Jev map + strict gate) ->
# (dedupe) -> (one bulk write to FalkorDB + fact vectors in Qdrant).
#
# The LLM is used *only* for entity/relation extraction (once per chunk, run
# concurrently up to `extract_concurrency`).  All ontology mapping is Jev's
# job and happens inside `map_text` — this module never talks to Jev directly.


class ChunkOutcome(BaseModel):
    """Per-chunk mapping result, trimmed for the HTTP response."""

    model_config = ConfigDict(extra="forbid")

    index: int
    chunk_id: str
    entities: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    triples_found: int = 0
    triples_valid: int = 0
    retries: int = 0
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class ExtractReport(BaseModel):
    """Everything the extract endpoint did, for one input text."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    group: str
    text_chars: int = 0
    resolved_chars: int = 0
    chunks: int = 0
    chunk_op: str = ""
    chunk_detail: str = ""
    triples_created: int = 0
    triples_rejected: int = 0
    rejected_details: list[str] = Field(default_factory=list)
    vector_status: str = ""
    warnings: list[str] = Field(default_factory=list)
    chunk_outcomes: list[ChunkOutcome] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    elapsed_s: float = 0.0


def new_doc_id() -> str:
    """Deterministic-ish doc id: unique per call, stable shape."""
    return f"doc-{uuid.uuid4().hex[:12]}"


async def extract_long_text(
    text: str,
    *,
    session: Any = None,
    graphiti: Any = None,
    deps: dict[str, Any] | None = None,
    group: str | None = None,
    doc_id: str | None = None,
    settings: Settings | None = None,
    embed_chunks: bool = True,
) -> ExtractReport:
    """Coref-resolve, chunk (no overlap), embed, extract, gate, and write.

    The LLM is called once per chunk (concurrently).  Jev does all ontology
    mapping inside `map_text`.  Only gate-passing triples reach FalkorDB.
    """
    import time

    s = settings or get_settings()
    if session is not None:
        session.require_open()
        graphiti = graphiti or session.graphiti
        deps = deps or session.deps
        group = group or session.group
    if graphiti is None:
        raise ValueError("pass either a `graphiti` instance or an open `OntologySession`")
    gate_deps = deps or get_jev_deps()
    group = group or s.jev_group
    doc_id = doc_id or new_doc_id()

    started = time.perf_counter()
    now = datetime.now(UTC)
    _ = now  # reserved: future per-doc created_at stamping

    # 1) Coreference resolution over the whole text (before chunking).
    #    `prepare_text` resolves corefs but does NOT chunk — it returns the
    #    resolved text; chunking is a separate disjoint split (step 2).
    prepared = await prepare_text(text, s)
    resolved = prepared.resolved_text
    coref_notes: list[str] = []
    if prepared.coref_chains == 0 and s.coref_enabled:
        coref_notes.append("coreference model found no chains; chunks use raw text")

    # 2) Disjoint chunks (no overlap) over the resolved text.
    from .chunking import split_no_overlap, verify_no_overlap

    chunks = split_no_overlap(resolved, s.chunk_size)
    # Safety net: the splitter is disjoint by design, but verify the contract
    # the endpoint promises ("no overlap") and surface any problem.
    overlap_issues = verify_no_overlap(resolved, chunks)
    if overlap_issues:
        coref_notes.append(
            "chunk overlap check: " + "; ".join(overlap_issues[:3])
        )

    # 3) Embed + store the chunks in Qdrant (best-effort; a mirror outage
    #    must not abort extraction).
    store = get_chunk_store(s)
    chunk_op, chunk_detail = "skipped", ""
    if embed_chunks:
        ensure = store.ensure_collection()
        records = [
            ChunkRecord(
                chunk_id=f"{doc_id}#{i}",
                doc_id=doc_id,
                text=c.text,
                start=c.start,
                end=c.end,
                index=i,
            )
            for i, c in enumerate(chunks)
        ]
        up = store.upsert(records, doc_id=doc_id, group_id=group)
        chunk_op = up.status
        chunk_detail = up.detail
        if not ensure.ok:
            coref_notes.append(f"chunk collection: {ensure.detail}")

    # 4) Concurrent per-chunk mapping (LLM extract + Jev map + gate).
    if session is None or session.jev is None:
        raise ValueError(
            "extract_long_text requires an open OntologySession (for the Jev client)"
        )
    jev = session.jev
    semaphore = asyncio.Semaphore(max(1, s.extract_concurrency))

    async def _one(index: int, chunk_text: str) -> tuple[int, MappingResult | None, str | None]:
        async with semaphore:
            try:
                mapping = await map_text(chunk_text, jev, gate_deps, settings=s)
                return index, mapping, None
            except Exception as exc:  # noqa: BLE001 — one bad chunk must not kill the run
                return index, None, f"{type(exc).__name__}: {exc}"

    results = await asyncio.gather(
        *[_one(i, c.text) for i, c in enumerate(chunks)]
    )

    # 5) Dedupe triples across chunks (same fact_key -> keep the first).
    seen: set[str] = set()
    valid: list[dict[str, Any]] = []
    rejected: list[str] = []
    outcomes: list[ChunkOutcome] = []
    usage_tally: dict[str, Any] = {}
    for index, mapping, error in sorted(results, key=lambda r: r[0]):
        if mapping is None:
            outcomes.append(
                ChunkOutcome(index=index, chunk_id=f"{doc_id}#{index}", error=error)
            )
            continue
        for key, value in (mapping.usage.model_dump() if hasattr(mapping.usage, "model_dump") else {}).items():
            if isinstance(value, (int, float)):
                usage_tally[key] = usage_tally.get(key, 0) + value
        found = len(mapping.triples)
        ok_n = 0
        for item in mapping.triples:
            key = triple_key_of(item.triple.model_dump())
            if not item.gate_ok:
                rejected.append(f"{key}: {'; '.join(item.gate_issues)}")
                continue
            if key in seen:
                continue
            seen.add(key)
            valid.append(item.triple.model_dump())
            ok_n += 1
        outcomes.append(
            ChunkOutcome(
                index=index,
                chunk_id=f"{doc_id}#{index}",
                entities=list(mapping.extraction.entities),
                relations=list(mapping.extraction.relations),
                triples_found=found,
                triples_valid=ok_n,
                retries=mapping.retries,
                notes=[n for n in mapping.notes if n][:5],
            )
        )

    # 6) One bulk write for the deduped, gate-passing triples.  `doc_id` is
    #    stamped on both the Falkor edges and the Qdrant fact payloads, so a
    #    later doc soft-delete can find every record this run produced.
    report = await manual_bulk_create(
        graphiti, gate_deps, valid, group=group, doc_id=doc_id
    )

    warnings = [*coref_notes, *report.warnings]
    return ExtractReport(
        doc_id=doc_id,
        group=group,
        text_chars=len(text),
        resolved_chars=len(resolved),
        chunks=len(chunks),
        chunk_op=chunk_op,
        chunk_detail=chunk_detail,
        triples_created=report.created,
        triples_rejected=report.rejected + len(rejected),
        rejected_details=[*report.rejected_details, *rejected][:200],
        vector_status=report.vector_status,
        warnings=warnings,
        chunk_outcomes=outcomes,
        usage=usage_tally,
        elapsed_s=round(time.perf_counter() - started, 3),
    )


__all__ = ["ExtractReport", "ChunkOutcome", "extract_long_text", "new_doc_id"]
