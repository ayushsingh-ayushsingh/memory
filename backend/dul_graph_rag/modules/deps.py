from __future__ import annotations

from functools import lru_cache
from typing import Any

from .gate import build_edge_types, build_entity_types
from .ontology import get_ontology
from .schema import load_schema
from .settings import Settings, get_settings


# %% Cell 16 — GATE DEPS: the *full* ontology, not the agent's scoped view
#
# `graphiti_crud_agent` scopes its edge map to the classes that appear in the
# checked-in facts, because Graphiti renders that map into an extraction
# prompt and a map over the whole ontology would blow the context window.
#
# This notebook is different: the **mapper** may pick *any* term of the
# ontology, so the gate has to know *every* admissible (class, class)
# combination. The map is therefore built over the whole ontology — every
# object property against every class — and the Graphiti custom entity/edge
# types are derived from the very same lineage, so the enforcement model and
# the ontology model can never drift apart.


def build_jev_deps(settings: Settings | None = None) -> dict[str, Any]:
    """Everything the pipeline needs to enforce DUL strictly."""
    _ = settings or get_settings()
    schema, ancestors, lineage = load_schema()
    classes = list(schema["classes"])
    properties = list(schema["object_properties"])

    entity_types = build_entity_types(classes)
    edge_models, edge_map, graphiti_map = build_edge_types(
        properties, lineage, ancestors, classes
    )

    ontology = get_ontology()
    counts = {
        "classes": len(ontology.classes),
        "object_properties": len(ontology.object_properties),
        "data_properties": len(ontology.data_properties),
    }
    counts["classes_in_gate"] = len(classes)

    return {
        "schema": schema,
        "ancestors": ancestors,
        "lineage": lineage,
        "edge_map": edge_map,
        "graphiti_map": graphiti_map,
        "entity_types": entity_types,
        "edge_types": edge_models,
        "counts": counts,
    }


@lru_cache(maxsize=1)
def get_jev_deps() -> dict[str, Any]:
    """Process-wide dependency snapshot (the ontology never changes at runtime)."""
    return build_jev_deps()


def deps_summary(deps: dict[str, Any] | None = None) -> dict[str, Any]:
    """Human-readable summary for the notebook."""
    d = deps or get_jev_deps()
    return {
        "classes_in_gate": len(d["schema"]["classes"]),
        "object_properties": len(d["schema"]["object_properties"]),
        "edge_map_pairs": len(d["edge_map"]),
        "edge_map_entries": sum(len(v) for v in d["edge_map"].values()),
        "entity_types": len(d["entity_types"]),
        "edge_types": len(d["edge_types"]),
        "graphiti_map_pairs": len(d["graphiti_map"]),
    }
