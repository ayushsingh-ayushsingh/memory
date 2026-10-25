"""End-to-end check: put a string in, then read the graph straight back out.

This is the exact workflow the pipeline is for, and it deliberately leaves the
triples in FalkorDB afterwards so the graph can be inspected in Redis
Insight / `redis-cli` / a FalkorDB client::

    cd backend
    uv run python notebooks/verify_ingest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = next(
    (p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file()),
    Path.cwd(),
)
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_BACKEND_ROOT / ".env")

from dul_graph_rag.modules.pipeline import ingest_blocking  # noqa: E402
from dul_graph_rag.modules.reports import triple_key_of  # noqa: E402
from dul_graph_rag.modules.runtime import section, table  # noqa: E402
from dul_graph_rag.modules.settings import get_settings  # noqa: E402

TEXT = (
    "Grace Hopper worked on the UNIVAC computer with Howard Aiken at Harvard "
    "in 1944. Aiken designed the UNIVAC, and Hopper developed its compiler."
)


def main() -> None:
    section("1 — Ingest (LLM extraction -> Jev mapping -> strict gate -> write)")
    report = ingest_blocking(TEXT)
    print(
        f"created={report.created}  rejected={report.rejected}  "
        f"vector_mirror={report.vector_status}"
    )
    table(
        [
            {
                "subject": r.subject,
                "relation": r.relation.rsplit("#", 1)[-1],
                "edge_context": r.relation_name,
                "object": r.object,
                "subject_class": r.subject_class.rsplit("#", 1)[-1],
                "object_class": r.object_class.rsplit("#", 1)[-1],
                "valid": r.valid,
                "detail": r.detail,
            }
            for r in report.mapping.gate_rows
        ],
        "Strict DUL gate verdict",
    )
    table(
        [
            {
                "fact_key": triple_key_of(t.triple.model_dump()),
                "pair_conf": round(t.pair_confidence, 3),
                "class_conf": round(t.class_confidence, 3),
                "property_conf": round(t.property_confidence, 3),
                "gate_ok": t.gate_ok,
            }
            for t in report.mapping.triples
        ],
        "Triples + Jev confidences",
    )

    section("2 — Read the graph back out of FalkorDB (raw, no ORM)")
    from falkordb import FalkorDB

    st = get_settings()
    client = FalkorDB(
        host=st.falkordb_host,
        port=st.falkordb_port,
        username=st.falkordb_user,
        password=st.falkordb_password,
    )
    graph = client.select_graph(st.graphiti_graph)

    rows = graph.query(
        "MATCH (a)-[r]->(b) WHERE r.group_id = $g "
        "RETURN a.name, labels(a), r.name, r.dul_relation, r.fact, b.name, labels(b) "
        "ORDER BY r.created_at DESC LIMIT 20",
        params={"g": st.jev_group},
    ).result_set
    table(
        [
            {
                "subject": a,
                "subject_labels": ",".join(al),
                "edge_name": en,
                "dul_relation": (dr or "").rsplit("#", 1)[-1],
                "fact": f,
                "object": b,
                "object_labels": ",".join(bl),
            }
            for a, al, en, dr, f, b, bl in rows
        ],
        f"FalkorDB '{st.graphiti_graph}' / group '{st.jev_group}' — raw edges",
    )
    total = graph.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    print(f"{len(rows)} edge(s) shown; {total} total in graph '{st.graphiti_graph}'")
    print("Left in place on purpose — inspect them in your FalkorDB client.")


if __name__ == "__main__":
    main()
