# %% marimo
"""DOLCE-enforced triple pipeline — thin driver.

Everything this notebook used to do inline now lives in `notebooks/modules/`
(see that package's `__init__` for the map). This file is deliberately short:
it is the *runnable* surface, and it exists so that "paste a string, get a
knowledge graph in FalkorDB" is a two-line operation.

Run it either way:

    uv run python notebooks/ontology_enforced_triplet.py      # plain python
    uv run marimo run notebooks/ontology_enforced_triplet.py  # marimo

Nothing here hardcodes a host, port, graph name, model id or vocabulary
term — all of it is read from `backend/.env`, `backend/graph.json` and
`backend/data/*.json` by `notebooks.modules.settings`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# %% Bootstrap: make `notebooks.modules` importable however this file runs.
#
# marimo (and `python path/to/file.py`) put the *notebook's own directory* on
# sys.path, not the backend root that holds `pyproject.toml`. Walk up to the
# real root so the package resolves regardless of the launcher.

_BACKEND_ROOT = next(
    (p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file()),
    Path.cwd(),
)
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# %% Imports

from dul_graph_rag.modules import (  # noqa: E402
    S,
    bulk_create,
    bulk_delete,
    create,
    delete,
    ingest,
    preflight,
    require_services,
    search,
    stats,
    update,
)
from dul_graph_rag.modules.reports import triple_key_of  # noqa: E402
from dul_graph_rag.modules.runtime import bullets, run, section, show, table  # noqa: E402
from dul_graph_rag.modules.session import OntologySession  # noqa: E402
from dul_graph_rag.modules.settings import get_settings  # noqa: E402

# %% THE ONE CELL YOU EDIT — paste your text here.
#
# Everything below is derived from this string: the entities and relations are
# extracted by the LLM, then mapped onto DOLCE terms by Jev, then checked
# against the strict ontology gate, and only then written to FalkorDB.

TEXT: str = """Ada Lovelace worked on the Analytical Engine with Charles Babbage
in London during the 1840s. Babbage designed the Analytical Engine, and
Lovelace wrote the first algorithm intended for it. The engine was a
physical artifact described by a plan."""

#: Optional: a question for the hybrid search cell. Leave `None` to reuse the
#: configured default from `.env`.
SEARCH_QUERY: str | None = None
SEARCH_LIMIT = 5  # clamped to DUL_LIMIT_MAX_SEARCH_RESULTS

#: Wipe the partition before writing. Off by default because it is destructive.
RESET_FIRST = False

# %% Cell A — Preflight: nothing runs until every service answers.

section("A — Service preflight")
SETTINGS = get_settings()
HEALTH_REPORT = preflight(SETTINGS)
table([svc.model_dump() for svc in HEALTH_REPORT.services], "Services")
require_services(HEALTH_REPORT, required=["falkordb", "jev"])

# %% Cell B — OPEN the session (preflight + ontology self-check + Jev + Graphiti)
#
# `OntologySession` verifies the DOLCE export against the counts it was
# written for (478 records / 77 classes / 112 object properties / ...) before
# opening anything, so a changed or truncated `graph.json` fails loudly.

section("B — Open session")
SESSION = OntologySession()
run(SESSION.open())
GROUP = SESSION.group
print(f"Partition (group): {GROUP}")
print(f"Graphiti store:    {SESSION.s.graphiti_graph}")
print(f"FalkorDB:          {SESSION.s.falkordb_host}:{SESSION.s.falkordb_port}")
print(f"Qdrant:            {SESSION.s.qdrant_url} (collection {SESSION.s.fact_collection})")
print(f"Jev model:         {SESSION.s.jev_model} (max {SESSION.s.jev_max_choices} choices)")
print(f"LLM (extraction):  {SESSION.s.groq_model}")
table(
    [
        {"metric": k, "expected": e, "actual": SESSION.checks["actual"].get(k), "match": e == SESSION.checks["actual"].get(k)}
        for k, e in SESSION.checks["expected"].items()
    ],
    "Verified DOLCE counts (must not change)",
)

if RESET_FIRST:
    section("B2 — RESET (destructive)")
    from dul_graph_rag.modules import reset as reset_group

    show(run(reset_group(SESSION.graphiti, group=GROUP)))

# %% Cell C — INGEST: text in, gated triples in FalkorDB.
#
# This is the whole pipeline in one call: LLM extraction -> Jev ontology
# mapping (with confidence scores) -> strict DUL gate -> bulk write of the
# triples that survived. Nothing unvalidated can reach the graph.

section("C — Ingest")
REPORT = run(ingest(TEXT, session=SESSION))
print(
    f"created={REPORT.created}  rejected={REPORT.rejected}  "
    f"vector_mirror={REPORT.vector_status}"
)
print(
    f"Jev usage: {REPORT.usage.calls} calls, {REPORT.usage.questions} questions "
    f"({REPORT.usage.input_tokens:,} in / {REPORT.usage.output_tokens:,} out tokens, "
    f"{REPORT.usage.elapsed_s:.1f}s)"
)
print(f"mapping: {REPORT.mapping.retries} retry pass(es), {len(REPORT.mapping.unmapped)} unmapped pair(s)")

# The strict-gate verdict, one row per proposed triple.
table(
    [
        {
            "subject": r.subject,
            "subject_class": r.subject_class.rsplit("#", 1)[-1],
            "relation": r.relation.rsplit("#", 1)[-1],
            "edge_context": r.relation_name,
            "object": r.object,
            "object_class": r.object_class.rsplit("#", 1)[-1],
            "valid": r.valid,
            "detail": r.detail,
        }
        for r in REPORT.mapping.gate_rows
    ],
    "Strict DUL gate (vocabulary + effective domain/range)",
)

# The Jev confidences that produced each triple.
table(
    [
        {
            "pair": t.pair_key,
            "surface_relation": t.surface_relation,
            "pair_conf": round(t.pair_confidence, 3),
            "class_conf": round(t.class_confidence, 3),
            "property_conf": round(t.property_confidence, 3),
            "tier": t.property_tier,
            "gate_ok": t.gate_ok,
            "issues": "; ".join(t.gate_issues) if t.gate_issues else "",
        }
        for t in REPORT.mapping.triples
    ],
    "Jev mapping confidences",
)

# What each surface pair was mapped to.
table(
    [
        {
            "entity": m.entity,
            "class": m.class_name,
            "confidence": round(m.confidence, 3),
            "levels": m.levels,
            "decided": m.decided,
            "path": " > ".join(p.rsplit("#", 1)[-1] for p in m.path[-3:]),
        }
        for m in REPORT.mapping.class_mappings.values()
    ],
    "Class mappings (Jev, entity -> DUL class)",
)
table(
    [
        {
            "relation": f"{m.subject} --{m.relation}--> {m.object}",
            "property": m.property_name,
            "confidence": round(m.confidence, 3),
            "tier": m.tier,
            "candidates": len(m.candidates),
            "near_misses": len(m.relaxed_candidates),
            "fallback": m.fallback_used,
        }
        for m in REPORT.mapping.property_mappings.values()
    ],
    "Property mappings (Jev, relation -> DUL object property)",
)
if REPORT.rejected_details:
    bullets(REPORT.rejected_details, "Rejected")
if REPORT.warnings:
    bullets(REPORT.warnings, "Warnings")
if REPORT.mapping.notes:
    bullets(REPORT.mapping.notes, "Mapping notes")

# %% Cell D — VERIFY: read the graph back out of FalkorDB.

section("D — Graph contents")
STATS = run(stats(SESSION.graphiti, group=GROUP))
print(
    f"{STATS['entities']} entities, {STATS['edges']} edges in '{STATS['group']}'"
)
table(STATS.get("sample", []), "Graph sample (s -rel-> o)")
table(
    [
        {"store": st.key, "graph": st.graph, "nodes": ", ".join(st.node_labels), "edges": ", ".join(st.edge_types)}
        for st in SESSION.graph_stores
    ],
    "Stores",
)

# %% Cell E — HYBRID SEARCH: graph fulltext + Qdrant vectors + jina rerank.

section("E — Search")
QUERY = SEARCH_QUERY or S.jev_demo_query
SEARCH_REPORT = run(
    search(SESSION.graphiti, SESSION.deps, QUERY, limit=SEARCH_LIMIT, group=GROUP)
)
print(f"query: {QUERY!r}   legs fused: {'+'.join(SEARCH_REPORT.legs) or '—'}")
table([h.model_dump() for h in SEARCH_REPORT.hits], "Search hits")
if SEARCH_REPORT.notes:
    bullets(SEARCH_REPORT.notes, "notes")

# %% Cell F — SINGLE CRUD: create -> update -> delete.
#
# The payload is *derived* from what the pipeline just wrote (never typed in),
# so the fact key -- and therefore the FalkorDB edge and its Qdrant vector --
# stays stable across the three operations. Fact keys are
# `subject|relation|object` and the ids are UUID5 of that key, so a re-run is
# an upsert, never a duplicate.

section("F — Single CRUD")
DERIVED = None
UPDATED = None
STATS_BEFORE = run(stats(SESSION.graphiti, group=GROUP))
if REPORT.mapping.triples:
    _first = next((t for t in REPORT.mapping.triples if t.gate_ok), None)
    if _first is not None:
        DERIVED = dict(_first.triple.model_dump())
        DERIVED["source"] = "driver-single"
        UPDATED = dict(DERIVED)
        UPDATED["fact_sentence"] = f"{DERIVED.get('fact_sentence', '')} (restated)"
        UPDATED["source"] = "driver-update"
        print(f"fact key: {triple_key_of(DERIVED)}")
        show(run(create(SESSION.graphiti, SESSION.deps, DERIVED, group=GROUP)))
        show(run(update(SESSION.graphiti, SESSION.deps, UPDATED, group=GROUP)))
        show(run(delete(SESSION.graphiti, triple_key_of(UPDATED), group=GROUP)))
else:
    print("F skipped — the mapping produced no gate-valid triple to derive from")

# %% Cell G — BULK CRUD: bulk create, then bulk delete.
#
# The rows are every gate-valid triple from the ingest above. NOTE that
# `bulk_delete` takes *fact keys* (`subject|relation|object`), not edge
# uuids -- the two are different identifiers and mixing them silently deletes
# nothing.

section("G — Bulk CRUD")
VALID = [t.triple.model_dump() for t in REPORT.mapping.triples if t.gate_ok]
print(f"{len(VALID)} gate-valid triple(s) in partition '{GROUP}'")
BULK_REPORT = run(bulk_create(SESSION.graphiti, SESSION.deps, VALID, group=GROUP))
show(BULK_REPORT)

FACT_KEYS = [triple_key_of(t) for t in VALID]
TARGETS = FACT_KEYS[-2:] if len(FACT_KEYS) >= 2 else FACT_KEYS
if TARGETS:
    print(f"bulk-deleting the last {len(TARGETS)} fact(s): {TARGETS}")
    show(run(bulk_delete(SESSION.graphiti, TARGETS, group=GROUP)))
else:
    print("G — nothing to bulk delete")

# %% Cell H — FINAL STATE.

section("H — Final stats")
FINAL = run(stats(SESSION.graphiti, group=GROUP))
print(
    f"before: {STATS_BEFORE['entities']} entities / {STATS_BEFORE['edges']} edges  ->  "
    f"after: {FINAL['entities']} entities / {FINAL['edges']} edges"
)

# %% Cell I — TEARDOWN.

section("I — Teardown")
run(SESSION.close())
print("Jev closed, Graphiti closed.")
