from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


from .clients import get_embedder
from .embeddings import embed_texts, rerank_scores
from .gate import (
    ProposedTriple,
    _short,
    dul_gate,
)
from .reports import (
    BulkDeleteReport,
    BulkReport,
    CreateReport,
    DeleteReport,
    SearchHit,
    SearchReport,
    WriteOutcome,
    edge_uuid,
    fact_payload,
    node_uuid,
    triple_key,
    triple_key_of,
)
from .settings import get_settings
from .vectors import VectorPoint, get_mirror, search_facts


# %% Cell 19 — CRUD WRITER: LLM-free gated writes + search (from tools/manual_crud.py)
#
# Unlike a Groq-proposed triple, these functions take triple dicts, enforce the
# same strict DUL gate, and write Entity nodes / RELATES_TO edges directly
# through Graphiti's bulk saver with the local fastembed embedder. No LLM call
# happens on any path here.
#
# Failure policy (prod-like): the graph (FalkorDB) is the system of record; the
# Qdrant mirror is an acceleration structure. A Qdrant outage therefore **never**
# fails a write: the report carries `vector_status` and a warning, and the
# missing vectors are replayed later with `sync_vectors()`.

def manual_default_group() -> str:
    """Logical partition used when a `manual_*` function gets no explicit group."""
    return get_settings().manual_group


# %% Deterministic ids (idempotent re-runs) — see Cell 11 for node_uuid /
# edge_uuid / triple_key_of; they are reused here unchanged.


# %% Gate table (sync, for notebook display)
def gate_table(
    triples: list[dict[str, Any]], deps: dict[str, Any]
) -> list[dict[str, Any]]:
    """Run dul_gate over each triple; return display rows (no writes)."""
    rows: list[dict[str, Any]] = []
    for t in triples:
        ok, issues = dul_gate(
            t, deps["schema"], deps["ancestors"], deps["lineage"], deps["edge_map"]
        )
        rows.append(
            {
                "subject": f"{t.get('subject_id', '?')} ({_short(str(t.get('subject_class', '?')))})",
                "relation": _short(str(t.get("relation", "?"))),
                "edge_name": str(t.get("relation_name", "")),
                "object": f"{t.get('object_id', '?')} ({_short(str(t.get('object_class', '?')))})",
                "valid": ok,
                "detail": "; ".join(issues) if issues else "gate passed",
            }
        )
    return rows


# %% Write core (LLM-free)
async def _bulk_write_chunked(
    graphiti: Any,
    nodes: list[Any],
    edges: list[Any],
    embedder: Any,
) -> None:
    """Write nodes then edges in bounded batches (settings-driven size).

    A single giant bulk write can exceed the server's request limits and time
    out halfway, leaving a half-written graph. Nodes go first (edges point at
    them by uuid), then edges are written in chunks of `graph_batch_size`.
    """
    from graphiti_core.utils.bulk_utils import add_nodes_and_edges_bulk

    size = max(1, get_settings().graph_batch_size)
    node_list = list(nodes)
    edge_list = list(edges)
    if node_list:
        await add_nodes_and_edges_bulk(
            graphiti.driver, [], [], node_list, [], embedder
        )
    for start in range(0, len(edge_list), size):
        await add_nodes_and_edges_bulk(
            graphiti.driver, [], [], [], edge_list[start : start + size], embedder
        )


async def _write_validated(
    graphiti: Any,
    triples: list[dict[str, Any]],
    group: str,
    *,
    version: int = 0,
    doc_id: str | None = None,
) -> WriteOutcome:
    """Bulk-save validated triples as Entity/RELATES_TO + Qdrant mirror.

    Returns a `WriteOutcome` describing both halves. All triples must already
    pass dul_gate. The graph write is authoritative; a vector-mirror outage is
    reported (`vector_status='deferred'`) instead of raising.

    `version` > 0 writes a *fresh* edge/point (id = key#vN) so the previous
    version is preserved and only flagged `superseded`.  `doc_id` is stamped on
    the edges so a whole document can be soft-deleted later.
    """
    from graphiti_core.edges import EntityEdge
    from graphiti_core.nodes import EntityNode


    now = datetime.now(UTC)
    iso_now = now.isoformat()
    nodes: dict[str, EntityNode] = {}
    edges: list[EntityEdge] = []
    for t in triples:
        prop = ProposedTriple(**t)
        for node_id, name, cls in (
            (prop.subject_id, prop.subject_name, prop.subject_class),
            (prop.object_id, prop.object_name, prop.object_class),
        ):
            if node_id not in nodes:
                nodes[node_id] = EntityNode(
                    uuid=node_uuid(group, node_id),
                    name=name,
                    group_id=group,
                    labels=[_short(cls)],
                    created_at=now,
                    summary=f"{name} ({_short(cls)})",
                    attributes={"dul_class": cls, "node_id": node_id},
                )
        key = triple_key_of(t)
        # versioned uuid: v0 keeps the legacy shape, vN is `key#vN`
        from .vectors import versioned_key

        edge_key = versioned_key(key, version)
        attrs: dict[str, Any] = {
            "dul_relation": prop.relation,
            "relation_name": prop.relation_name,
            "subject_id": prop.subject_id,
            "object_id": prop.object_id,
            "fact_key": key,
            "source": prop.source,
            "version": version,
            "created_at": iso_now,
            "deleted": False,
            "superseded": False,
        }
        if doc_id:
            attrs["doc_id"] = doc_id
        edges.append(
            EntityEdge(
                uuid=edge_uuid(group, edge_key),
                group_id=group,
                source_node_uuid=node_uuid(group, prop.subject_id),
                target_node_uuid=node_uuid(group, prop.object_id),
                created_at=now,
                name=_short(prop.relation),
                fact=prop.fact_sentence,
                episodes=[],
                valid_at=now,
                reference_time=now,
                attributes=attrs,
            )
        )
    await _bulk_write_chunked(graphiti, list(nodes.values()), edges, get_embedder())

    props = [ProposedTriple(**t) for t in triples]
    keys = [triple_key_of(t) for t in triples]
    vectors = embed_texts([p.fact_sentence for p in props])
    mirror = get_mirror()
    ensure = mirror.ensure_collection()
    result = mirror.upsert(
        [
            VectorPoint(
                key=key,
                vector=vec,
                payload=fact_payload(
                    prop, key, group, version=version, doc_id=doc_id
                ),
                group=group,
                version=version,
            )
            for key, prop, vec in zip(keys, props, vectors, strict=True)
        ]
    )
    warnings: list[str] = []
    for op in (ensure, result):
        if not op.ok:
            warnings.append(
                f"vector mirror {op.status}: {op.detail or 'unknown error'} — "
                "facts are in the graph; replay with manual_sync_vectors()"
            )
    return WriteOutcome(
        node_uuids=[n.uuid for n in nodes.values()],
        edge_uuids=[e.uuid for e in edges],
        vector_status=result.status,
        vector_detail=result.detail,
        warnings=warnings,
    )


# %% Create (single + bulk)
async def manual_create_triple(
    graphiti: Any,
    deps: dict[str, Any],
    triple: dict[str, Any],
    group: str | None = None,
) -> CreateReport:
    """Gate one triple; write it LLM-free. Never writes unvalidated data."""

    group = group or manual_default_group()
    key = triple_key(triple)
    ok, issues = dul_gate(
        triple, deps["schema"], deps["ancestors"], deps["lineage"], deps["edge_map"]
    )
    if not ok:
        return CreateReport(status="rejected", fact_key=key, issues=issues)
    outcome = await _write_validated(graphiti, [triple], group)
    return CreateReport(
        status="created",
        fact_key=key,
        episode_uuid=None,
        vector_status=outcome.vector_status,
        warnings=outcome.warnings,
    )


async def manual_bulk_create(
    graphiti: Any,
    deps: dict[str, Any],
    triples: list[dict[str, Any]],
    group: str | None = None,
    *,
    doc_id: str | None = None,
) -> BulkReport:
    """Gate each triple; write the valid subset LLM-free (no episodes).

    `doc_id` is stamped on both the Falkor edge attributes and the Qdrant
    fact payload, so a later `manual_bulk_delete_docs` can find every record
    this call produced (in both stores) and soft-flag it.
    """

    group = group or manual_default_group()
    valid: list[dict[str, Any]] = []
    rejected: list[str] = []
    for t in triples:
        ok, issues = dul_gate(
            t, deps["schema"], deps["ancestors"], deps["lineage"], deps["edge_map"]
        )
        if ok:
            valid.append(t)
        else:
            rejected.append(f"{triple_key(t)}: {'; '.join(issues)}")
    uuids: list[str] = []
    vector_status = "skipped"
    warnings: list[str] = []
    if valid:
        outcome = await _write_validated(graphiti, valid, group, doc_id=doc_id)
        uuids = outcome.edge_uuids
        vector_status = outcome.vector_status
        warnings = outcome.warnings
    return BulkReport(
        # Count what was actually written, not what was handed to the
        # writer: `_write_validated` returns the edge uuids it managed to
        # persist, and one that failed must not be reported as created.
        created=len(uuids),
        rejected=len(rejected),
        # BUG FIX: this used to be `episode_uuids=uuids`, which is not a
        # field of `BulkReport` (the field is `edge_uuids`). With
        # `extra="forbid"` every bulk create raised a pydantic
        # `ValidationError` before anything was written.
        edge_uuids=uuids,
        rejected_details=rejected,
        vector_status=vector_status,
        warnings=warnings,
    )


# %% Search (Graphiti fulltext + Qdrant facts + Qdrant chunks, jina rerank)
async def manual_search(
    graphiti: Any,
    deps: dict[str, Any],
    query: str,
    limit: int | None = None,
    group: str | None = None,
    *,
    include_deleted: bool = False,
    include_superseded: bool = False,
    include_chunks: bool = True,
) -> SearchReport:
    """Fulltext + semantic search across FalkorDB and Qdrant, reranked.

    Three legs are queried in parallel-ish sequence:
      1. FalkorDB fulltext over RELATES_TO edges (graph facts).
      2. Qdrant semantic over the *fact* mirror (graph facts' vectors).
      3. Qdrant semantic over the *chunk* store (raw source text, no-overlap).

    Every hit is reranked by the local jina cross-encoder, then scaled by a
    recency half-life decay and soft-flag weights (superseded/deleted), so
    past data is de-weighted, never removed.  Embedding and reranking run in
    a worker thread so the event loop is never blocked.
    """
    import asyncio as _asyncio

    from graphiti_core.search.search_filters import SearchFilters

    from .chunk_store import get_chunk_store
    from .temporal import weighted_score

    _ = deps  # deps kept for signature parity with agent tools; unused here.
    group = group or manual_default_group()
    s = get_settings()
    limit = s.default_search_limit if limit is None else limit
    limit = max(1, min(limit, s.max_search_limit))

    candidates: list[tuple[str, str, str | None, str | None, bool, bool]] = []
    # (text, provenance, created_at, ref, deleted, superseded)
    legs: list[str] = []
    notes: list[str] = []

    # --- Leg 1: FalkorDB fulltext over edge facts
    try:
        edges = await graphiti.driver.search_ops.edge_fulltext_search(
            graphiti.driver,
            query,
            SearchFilters(),
            group_ids=[group],
            limit=s.graph_fetch_multiplier * limit,
        )
        for e in edges:
            fact = getattr(e, "fact", None)
            if not fact:
                continue
            attrs = getattr(e, "attributes", {}) or {}
            created = attrs.get("created_at") or getattr(e, "created_at", None)
            deleted = bool(attrs.get("deleted", False))
            superseded = bool(attrs.get("superseded", False))
            candidates.append(
                (
                    fact,
                    "falkor",
                    str(created) if created else None,
                    attrs.get("fact_key"),
                    deleted,
                    superseded,
                )
            )
        if edges:
            legs.append("falkor")
    except Exception as exc:  # noqa: BLE001 — other legs can still answer
        notes.append(f"falkor fulltext leg unavailable: {type(exc).__name__}: {exc}")

    # --- Embed the query once, reuse for both Qdrant legs (in a thread).
    vector = await _asyncio.to_thread(lambda: embed_texts([query])[0])

    # --- Leg 2: Qdrant semantic over the fact mirror
    try:
        fact_hits = await _asyncio.to_thread(
            lambda: search_facts(
                vector,
                limit=limit * s.graph_fetch_multiplier,
                group_id=group,
                include_deleted=include_deleted,
                include_superseded=include_superseded,
            )
        )
        if fact_hits.ok:
            for hit in fact_hits.data.get("points", []):
                payload = hit.payload or {}
                if payload.get("fact_sentence"):
                    candidates.append(
                        (
                            payload["fact_sentence"],
                            "qdrant-fact",
                            payload.get("created_at"),
                            payload.get("fact_key"),
                            bool(payload.get("deleted", False)),
                            bool(payload.get("superseded", False)),
                        )
                    )
            legs.append("qdrant-fact")
        else:
            notes.append(f"fact mirror unavailable: {fact_hits.detail}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"qdrant fact leg error: {type(exc).__name__}: {exc}")

    # --- Leg 3: Qdrant semantic over the raw chunk store
    if include_chunks:
        try:
            store = get_chunk_store(s)
            chunk_hits = await _asyncio.to_thread(
                lambda: store.search(
                    vector,
                    limit=limit * s.graph_fetch_multiplier,
                    group_id=group,
                    include_deleted=include_deleted,
                    include_superseded=include_superseded,
                )
            )
            if chunk_hits.ok:
                for hit in chunk_hits.data.get("points", []):
                    payload = hit.payload or {}
                    if payload.get("text"):
                        candidates.append(
                            (
                                payload["text"],
                                "qdrant-chunk",
                                payload.get("created_at"),
                                payload.get("doc_id"),
                                bool(payload.get("deleted", False)),
                                bool(payload.get("superseded", False)),
                            )
                        )
                legs.append("qdrant-chunk")
            elif chunk_hits.status not in ("disabled", "missing"):
                notes.append(f"chunk store unavailable: {chunk_hits.detail}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"qdrant chunk leg error: {type(exc).__name__}: {exc}")

    if not candidates:
        return SearchReport(query=query, hits=[], legs=legs, notes=notes)

    # --- Reconcile flags with FalkorDB as the system of record.
    # The Qdrant mirror is best-effort: a flag write can legitimately fail (it
    # never raises), so a fact may be `deleted` in the graph but still `live`
    # in the mirror. Falkor's flag state therefore overrides the mirror's for
    # any fact_key both legs know about, so a graph-deleted fact can never
    # surface through the vector leg.
    falkor_flags: dict[str, tuple[bool, bool]] = {}
    for _t, _p, _c, key, _d, _s in candidates:
        if _p == "falkor" and key:
            falkor_flags[str(key)] = (_d, _s)
    if falkor_flags:
        reconciled: list[tuple[str, str, str | None, str | None, bool, bool]] = []
        for text, prov, created, key, deleted, superseded in candidates:
            if prov != "falkor" and key and str(key) in falkor_flags:
                deleted, superseded = falkor_flags[str(key)]
            reconciled.append((text, prov, created, key, deleted, superseded))
        candidates = reconciled

    # --- Rerank in a worker thread (cross-encoder is CPU-bound).
    texts = [c[0] for c in candidates]
    scores = await _asyncio.to_thread(lambda: rerank_scores(query, texts))

    # --- Apply recency decay + soft-flag weights, then rank.
    # The same fact can arrive from several legs (Falkor fulltext + Qdrant
    # fact mirror).  Dedup by `ref` (the fact_key / doc_id), keeping the
    # highest-weighted copy so one fact occupies one slot.
    best: dict[str, tuple[float, tuple[str, str, str | None, str | None, bool, bool]]] = {}
    for candidate, base in zip(candidates, scores, strict=True):
        text, prov, created, key, deleted, superseded = candidate
        weight = weighted_score(
            base,
            created,
            deleted=deleted,
            superseded=superseded,
            include_deleted=include_deleted,
            include_superseded=include_superseded,
        )
        if weight is None:
            continue
        # Facts dedup across legs on `key` alone (same fact_key from either
        # leg is the same fact); chunk texts have no fact_key so they are
        # keyed by their text to avoid collapsing distinct chunks.
        dedup_key = str(key) if key else f"{prov}:{text[:120]}"
        current = best.get(dedup_key)
        if current is None or weight > current[0]:
            best[dedup_key] = (weight, candidate)
    ranked = sorted(best.values(), key=lambda p: p[0], reverse=True)

    hits = [
        SearchHit(
            fact=text,
            score=float(score),
            provenance=prov,
            created_at=created,
            ref=key,
        )
        for score, (text, prov, created, key, _d, _s) in ranked[:limit]
    ]
    return SearchReport(query=query, hits=hits, legs=legs, notes=notes)


# %% Update (soft-supersede the old value, write a new one)
async def manual_update_triple(
    graphiti: Any,
    deps: dict[str, Any],
    triple: dict[str, Any],
    group: str | None = None,
    *,
    supersedes: list[str] | None = None,
) -> CreateReport:
    """Update = gate + soft-supersede the old value(s) + write the new one.

    Because a fact's key is ``subject|relation|object``, changing the object
    changes the key, so the old fact cannot be found by key alone.  The facts
    that get superseded are therefore the **live facts for the same
    (subject, relation)** — i.e. the current value of the property being
    updated — plus any explicit ``supersedes`` fact_keys.

    Nothing is deleted: old facts keep their history and are only flagged
    ``superseded`` (de-weighted in search).  The new fact is written as a
    version of its own fact_key: version 0 for a brand-new key, max+1 when
    re-asserting an existing one.
    """
    from .temporal import flag_edge
    from .vectors import get_mirror, versioned_key

    group = group or manual_default_group()
    new_key = triple_key(triple)
    ok, issues = dul_gate(
        triple, deps["schema"], deps["ancestors"], deps["lineage"], deps["edge_map"]
    )
    if not ok:
        return CreateReport(status="rejected", fact_key=new_key, issues=issues)

    subject_id = str(triple.get("subject_id", ""))
    relation_short = _short(str(triple.get("relation", "")))
    prefix = f"{subject_id}|{relation_short}|"
    now_iso = datetime.now(UTC).isoformat()
    warnings: list[str] = []

    # 1) Find the live facts to supersede: same (subject, relation) value(s)
    #    plus any explicitly named old keys.
    old_keys: set[str] = set()
    try:
        rows, _, _ = await graphiti.driver.execute_query(
            "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g "
            "AND coalesce(r.deleted,false) = false "
            "AND coalesce(r.superseded,false) = false "
            "AND (r.fact_key STARTS WITH $prefix OR r.fact_key IN $extra) "
            "RETURN DISTINCT r.fact_key AS k",
            g=group,
            prefix=prefix,
            extra=list(supersedes or []),
        )
        old_keys = {str(r["k"]) for r in rows if r.get("k")}
    except Exception as exc:  # noqa: BLE001 — the new write can still land
        warnings.append(f"could not list old fact(s): {type(exc).__name__}: {exc}")

    # 2) Work out the new fact_key's version: 0 when it is brand new,
    #    max+1 when re-asserting an existing key.
    new_version = 0
    try:
        rows, _, _ = await graphiti.driver.execute_query(
            "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g AND r.fact_key = $k "
            "RETURN count(r) AS c, max(coalesce(r.version,0)) AS mv",
            g=group,
            k=new_key,
        )
        count = int(rows[0].get("c") or 0) if rows else 0
        mv = int(rows[0].get("mv") or 0) if rows else 0
        new_version = (mv + 1) if count > 0 else 0
    except Exception:  # noqa: BLE001 — default to version 0
        new_version = 0

    new_edge_uuid = edge_uuid(group, versioned_key(new_key, new_version))

    # 3) Soft-supersede every old fact: Falkor flag + Qdrant flag.
    for old_key in old_keys:
        try:
            rows, _, _ = await graphiti.driver.execute_query(
                "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g AND r.fact_key = $k "
                "RETURN r.uuid AS u",
                g=group,
                k=old_key,
            )
            for r in rows:
                if r.get("u"):
                    await flag_edge(
                        graphiti.driver,
                        str(r["u"]),
                        group,
                        superseded_at=now_iso,
                        superseded_by=new_edge_uuid,
                    )
            # mark superseded=true so the search leg's attribute read sees it
            await graphiti.driver.execute_query(
                "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g AND r.fact_key = $k "
                "SET r.superseded = true",
                g=group,
                k=old_key,
            )
        except Exception as exc:  # noqa: BLE001 — the new write can still land
            warnings.append(f"could not flag old '{old_key}': {type(exc).__name__}: {exc}")
        # Mirror the flag onto the Qdrant point(s) of the old key (best-effort).
        try:
            get_mirror().flag(
                [old_key], group=group, superseded=True, superseded_by=new_edge_uuid
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"could not flag old vector '{old_key}': {type(exc).__name__}: {exc}")

    # 4) Write the new fact at its version.
    outcome = await _write_validated(graphiti, [triple], group, version=new_version)
    warnings.extend(outcome.warnings)
    return CreateReport(
        status="updated",
        fact_key=new_key,
        episode_uuid=None,
        vector_status=outcome.vector_status,
        warnings=warnings,
    )


# %% Delete (single + bulk) — soft-flag only, nothing is ever removed
async def manual_delete_triple(
    graphiti: Any, fact_key: str, group: str | None = None
) -> DeleteReport:
    """Soft-delete every version of one fact (by fact_key) in FalkorDB + Qdrant.

    The edge(s) get `deleted_at` set (and `deleted=true` in attributes) so they
    are hidden by default in search but never removed from the graph.  The same
    flag is mirrored onto the Qdrant point(s).
    """

    group = group or manual_default_group()
    now_iso = datetime.now(UTC).isoformat()
    from .temporal import flag_edges_by_key
    from .vectors import get_mirror

    warnings: list[str] = []
    try:
        flagged = await flag_edges_by_key(
            graphiti.driver, [fact_key], group, deleted_at=now_iso
        )
        # Also stamp `deleted=true` so the search leg's attribute read sees it.
        rows, _, _ = await graphiti.driver.execute_query(
            "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g AND r.fact_key = $k "
            "SET r.deleted = true RETURN count(r) AS n",
            g=group,
            k=fact_key,
        )
        deleted_n = int(rows[0].get("n", 0)) if rows else flagged
    except Exception as exc:  # noqa: BLE001 — surfaced in report
        return DeleteReport(
            status="error",
            fact_key=fact_key,
            detail=str(exc)[: get_settings().error_detail_max_len],
        )

    vector = get_mirror().flag([fact_key], group=group, deleted=True, deleted_at=now_iso)
    if not vector.ok:
        warnings.append(
            f"vector mirror {vector.status}: {vector.detail} — "
            "the flag can be replayed with manual_sync_vectors()"
        )
    if not deleted_n:
        # The edge is absent from FalkorDB (the system of record).  If the
        # vector flag also failed, the fact exists nowhere -> "not-found";
        # if only the mirror missed it, the edge is what is missing.
        status = "not-found" if not vector.ok else "qdrant-flagged-edge-missing"
        return DeleteReport(
            status=status,
            fact_key=fact_key,
            detail=f"group={group}",
            vector_status=vector.status,
            warnings=warnings,
        )
    return DeleteReport(
        status="deleted",
        fact_key=fact_key,
        detail=f"group={group} flagged={deleted_n}",
        vector_status=vector.status,
        warnings=warnings,
    )


async def manual_bulk_delete(
    graphiti: Any, fact_keys: list[str], group: str | None = None
) -> BulkDeleteReport:
    """Soft-delete many facts by fact_key; report per-key outcomes."""
    group = group or manual_default_group()
    deleted, missing, details, warnings = 0, 0, [], []
    for key in fact_keys:
        rep = await manual_delete_triple(graphiti, key, group)
        if rep.status == "deleted":
            deleted += 1
        else:
            missing += 1
        details.append(f"{key}: {rep.status}")
        warnings.extend(rep.warnings)
    return BulkDeleteReport(
        deleted=deleted, missing=missing, details=details, warnings=warnings
    )


async def manual_bulk_delete_docs(
    graphiti: Any, doc_ids: list[str], group: str | None = None
) -> dict[str, Any]:
    """Soft-delete every fact and chunk that came from the given documents.

    This is the "bulk deletion" path for the extract endpoint: a whole ingest
    run can be retired without touching anything else.
    """
    from datetime import UTC as _UTC, datetime as _dt

    from .chunk_store import get_chunk_store

    from .settings import get_settings as _gs

    group = group or manual_default_group()
    now_iso = _dt.now(_UTC).isoformat()
    s = _gs()
    flagged_edges = 0
    warnings: list[str] = []
    for doc_id in doc_ids:
        try:
            rows, _, _ = await graphiti.driver.execute_query(
                "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g AND r.doc_id = $d "
                "SET r.deleted = true, r.deleted_at = $t RETURN count(r) AS n",
                g=group,
                d=doc_id,
                t=now_iso,
            )
            flagged_edges += int(rows[0].get("n", 0)) if rows else 0
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"doc {doc_id}: edge flag failed: {type(exc).__name__}: {exc}")
        # Mirror the flag onto the Qdrant fact points of this doc (best-effort).
        try:
            from .vectors import get_mirror

            get_mirror().flag_by_doc(doc_id, group=group, deleted=True, deleted_at=now_iso)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"doc {doc_id}: vector flag failed: {type(exc).__name__}: {exc}")
        # Flag the raw chunks too.
        try:
            get_chunk_store(s).flag_doc(doc_id, deleted=True, deleted_at=now_iso)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"doc {doc_id}: chunk flag failed: {type(exc).__name__}: {exc}")
    return {
        "group": group,
        "docs": len(doc_ids),
        "edges_flagged": flagged_edges,
        "warnings": warnings,
    }


# %% Reset (fresh graph on every run)
async def manual_reset_group(
    graphiti: Any, group: str | None = None
) -> dict[str, Any]:
    """Wipe one manual group: Entity nodes (+edges) from FalkorDB, vectors from Qdrant.

    Graphs are cheap and created on demand: get_graphiti() rebuilds indices and
    the next bulk/single create repopulates. Call this first in fresh runs.
    """

    group = group or manual_default_group()
    await graphiti.driver.execute_query(
        "MATCH (n:Entity) WHERE n.group_id = $g DETACH DELETE n", g=group
    )
    # The graph wipe already succeeded; the mirror wipe is best-effort and is
    # reported instead of raising (same failure policy as every write).
    wiped = get_mirror().wipe_group(group)
    mirror_status = "up" if wiped.ok else "unreachable"
    if wiped.status == "disabled":
        mirror_status = "disabled"
    return {
        "group": group,
        "qdrant_points_removed": wiped.count,
        "qdrant_status": mirror_status,
        "qdrant_detail": wiped.detail,
    }


# %% Vector-mirror repair (replay writes that happened during an outage)
async def manual_prune_vectors() -> dict[str, Any]:
    """Remove mirror points whose id no longer matches the current scheme."""

    result = get_mirror().prune_stale()
    return {
        "vector_status": result.status,
        "pruned": result.count,
        "detail": result.detail,
    }


async def manual_sync_vectors(
    graphiti: Any, group: str | None = None
) -> dict[str, Any]:
    """Backfill the vector mirror from the graph (graph = source of truth).

    Use after a Qdrant outage: every fact edge in the group that has no
    vector yet is re-embedded and upserted.
    """

    group = group or manual_default_group()
    rows, _, _ = await graphiti.driver.execute_query(
        "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g "
        "RETURN r.fact_key AS key, r.fact AS fact",
        g=group,
    )
    facts = [(str(r.get("key")), str(r.get("fact"))) for r in rows if r.get("key")]
    result = get_mirror().sync_missing(facts, group=group)
    return {
        "group": group,
        "graph_facts": len(facts),
        "vector_status": result.status,
        "backfilled": result.count,
        "detail": result.detail,
    }


# %% Stats (for notebook display)
async def manual_stats(
    graphiti: Any, group: str | None = None
) -> dict[str, Any]:
    """Entity/edge counts + flags + sample + Qdrant counts for one group."""

    from .chunk_store import get_chunk_store

    group = group or manual_default_group()
    entity_rows, _, _ = await graphiti.driver.execute_query(
        "MATCH (n:Entity) WHERE n.group_id = $g RETURN count(n) AS c", g=group
    )
    edge_rows, _, _ = await graphiti.driver.execute_query(
        "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g RETURN count(r) AS c",
        g=group,
    )
    flag_rows, _, _ = await graphiti.driver.execute_query(
        "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g "
        "RETURN sum(CASE WHEN coalesce(r.deleted, false) THEN 1 ELSE 0 END) AS deleted, "
        "sum(CASE WHEN coalesce(r.superseded, false) THEN 1 ELSE 0 END) AS superseded, "
        "sum(CASE WHEN NOT coalesce(r.deleted, false) AND NOT coalesce(r.superseded, false) "
        "THEN 1 ELSE 0 END) AS live",
        g=group,
    )
    doc_rows, _, _ = await graphiti.driver.execute_query(
        "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g AND r.doc_id IS NOT NULL "
        "RETURN count(DISTINCT r.doc_id) AS c",
        g=group,
    )
    sample_rows, _, _ = await graphiti.driver.execute_query(
        "MATCH (s:Entity)-[r:RELATES_TO]->(o:Entity) "
        "WHERE s.group_id = $g AND r.group_id = $g "
        "RETURN s.name AS s, r.name AS rel, r.fact AS fact, o.name AS o LIMIT 25",
        g=group,
    )
    mirror = get_mirror().status()
    qdrant_n = mirror.count if mirror.ok else -1
    chunk_status = get_chunk_store().status()
    flags = flag_rows[0] if flag_rows else {}
    return {
        "group": group,
        "entities": entity_rows[0].get("c", 0) if entity_rows else 0,
        "edges": edge_rows[0].get("c", 0) if edge_rows else 0,
        "edges_live": flags.get("live", 0),
        "edges_deleted": flags.get("deleted", 0),
        "edges_superseded": flags.get("superseded", 0),
        "docs": doc_rows[0].get("c", 0) if doc_rows else 0,
        "qdrant_points_total": qdrant_n,
        "qdrant_status": mirror.status,
        "chunk_points_total": chunk_status.count,
        "chunk_status": chunk_status.status,
        "sample": sample_rows,
    }
