"""DOLCE-enforced triple pipeline, split out of `ontology_enforced_triplet.py`.

The single-file notebook this package was carved out of ran to ~6,200 lines,
which made it impossible to navigate. Each module here owns one concern and
knows only about the ones below it::

    paths            filesystem anchors (.env, graph.json, data/)      [leaf]
      settings       every endpoint / store / model id, from env
        runtime      one event loop + notebook printers
        preflight    are FalkorDB, Qdrant, Groq and Jev up?
        stores       which FalkorDB graph holds what
        schema       offline DUL snapshot (data/dul_schema.json)
        ontology     the DOLCE export (graph.json) + the verified self-check
          gate       vocabulary + effective domain/range + custom types
            reports  write/search report models + deterministic fact ids
          embeddings local fastembed embeddings + jina cross-encoder
            vectors  best-effort Qdrant mirror of the fact edges
        clients      Graphiti on FalkorDB + the Groq LLM
        jev          the Jev `Choice` client (budgeted, accounted)
          deps       the full ontology handed to the gate
            mapper_types / mapper   Jev maps classes and properties
          extraction the ONLY place an LLM runs (entity/relation extraction)
            mapping  Jev maps the pairs, the gate validates, retry on failure
              crud   LLM-free gated writes + hybrid search
                facade     group-aware wrappers
                  session  preflight + self-check + open/close
                    pipeline   text in -> gated triples in FalkorDB   [top]

The single entry point most callers want is `pipeline.ingest_blocking`.
"""

from __future__ import annotations

from .extraction import ExtractionResult, IngestReport, MappingResult
from .facade import (
    bulk_create,
    bulk_delete,
    create,
    default_group,
    delete,
    reset,
    search,
    stats,
    sync_vectors,
    update,
)
from .gate import ProposedTriple, dul_gate, validate_fact
from .mapping import map_ontology, map_text
from .paths import DATA_DIR, ENV_FILE, ONTOLOGY_GRAPH_PATH, PROJECT_ROOT
from .pipeline import ingest, ingest_blocking, plan
from .preflight import HealthReport, ServiceStatus, ServiceUnavailable, preflight, require_services
from .reports import BulkReport, CreateReport, DeleteReport, SearchHit, SearchReport
from .schema import is_subclass_of, load_schema
from .session import OntologySelfCheckError, OntologySession, close_session, open_session
from .settings import S, Settings, get_settings, reset_settings_cache

__all__ = [
    # -- paths / settings
    "PROJECT_ROOT",
    "ENV_FILE",
    "DATA_DIR",
    "ONTOLOGY_GRAPH_PATH",
    "Settings",
    "S",
    "get_settings",
    "reset_settings_cache",
    # -- ontology
    "load_schema",
    "is_subclass_of",
    # -- gate
    "ProposedTriple",
    "dul_gate",
    "validate_fact",
    # -- mapping / extraction
    "ExtractionResult",
    "MappingResult",
    "IngestReport",
    "map_ontology",
    "map_text",
    # -- CRUD
    "CreateReport",
    "BulkReport",
    "DeleteReport",
    "SearchReport",
    "SearchHit",
    "create",
    "bulk_create",
    "update",
    "delete",
    "bulk_delete",
    "search",
    "stats",
    "reset",
    "sync_vectors",
    "default_group",
    # -- lifecycle / entry point
    "HealthReport",
    "ServiceStatus",
    "ServiceUnavailable",
    "preflight",
    "require_services",
    "OntologySession",
    "OntologySelfCheckError",
    "open_session",
    "close_session",
    "ingest",
    "ingest_blocking",
    "plan",
]
