from __future__ import annotations

from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    create_model,
)

from .ontology import (
    local_name,
)
from .schema import is_subclass_of
from .settings import S


# %% Cell 09 — STRICT VALIDATION: vocabulary + effective domain/range
#
# This is the half of the gate that reads the snapshot lineage. Fail-closed:
# an unknown term, a missing domain/range or a type mismatch is a rejection
# with a message that is fed back to Jev.


def validate_fact(
    fact: dict[str, Any],
    schema: dict[str, Any],
    ancestors: dict[str, set[str]],
    property_lineage: dict[str, dict],
) -> tuple[bool, str]:
    """Vocabulary + effective domain/range subclass check (fail-closed)."""
    classes = set(schema["classes"])
    props = set(schema["object_properties"])
    for key in (
        "subject_id",
        "object_id",
        "subject_class",
        "object_class",
        "relation",
        "relation_name",
    ):
        if not fact.get(key) or (
            isinstance(fact.get(key), str) and not fact.get(key).strip()
        ):
            return False, f"missing required field: {key}"
    if len(fact["relation_name"].strip()) > 200:
        return False, "relation_name too long (max 200 chars)"
    sc, oc, rel = (
        fact["subject_class"],
        fact["object_class"],
        fact["relation"],
    )
    if sc not in classes:
        return False, f"unknown subject_class (not in DUL): {sc}"
    if oc not in classes:
        return False, f"unknown object_class (not in DUL): {oc}"
    if rel not in props:
        return False, f"unknown relation (not in DUL): {rel}"
    lineage = property_lineage.get(rel, {"domain": [], "range": []})
    domains, ranges = lineage["domain"], lineage["range"]
    if not domains or not ranges:
        return (
            False,
            (
                f"strict reject: {local_name(rel)} has no named domain+range "
                f"(domain={domains}, range={ranges})"
            ),
        )
    bad_d = [d for d in domains if not is_subclass_of(sc, d, ancestors)]
    bad_r = [r for r in ranges if not is_subclass_of(oc, r, ancestors)]
    if bad_d or bad_r:
        parts = []
        if bad_d:
            parts.append(
                f"subject {local_name(sc)} not subclass of domain "
                f"{', '.join(local_name(d) for d in bad_d)}"
            )
        if bad_r:
            parts.append(
                f"object {local_name(oc)} not subclass of range "
                f"{', '.join(local_name(r) for r in bad_r)}"
            )
        return False, "domain/range mismatch: " + "; ".join(parts)
    if lineage.get("symmetric"):
        # Symmetric P(s,o) entails P(o,s): both ends must satisfy both sides.
        rev_bad_d = [d for d in domains if not is_subclass_of(oc, d, ancestors)]
        rev_bad_r = [r for r in ranges if not is_subclass_of(sc, r, ancestors)]
        if rev_bad_d or rev_bad_r:
            return False, (
                "symmetric mismatch: mirror "
                f"{local_name(oc)} -[{local_name(rel)}]-> {local_name(sc)} "
                "would violate domain/range "
                f"(object {local_name(oc)} vs domain "
                f"{', '.join(local_name(d) for d in rev_bad_d) or '-'}; "
                f"subject {local_name(sc)} vs range "
                f"{', '.join(local_name(r) for r in rev_bad_r) or '-'})"
            )
    flags = lineage.get("characteristics", [])
    note = f" [{','.join(flags)}]" if flags else ""
    return True, (
        f"OK: {local_name(sc)} -[{local_name(rel)}]-> {local_name(oc)}{note} "
        f"(domain {', '.join(local_name(d) for d in domains)}; "
        f"range {', '.join(local_name(r) for r in ranges)})"
    )


# %% Cell 10 — DUL CUSTOM TYPES + THE STRICT GATE
#
# Graphiti custom entity/edge types and the edge_type_map are derived at
# runtime from the snapshots — nothing is hardcoded, so a snapshot update
# changes the enforcement with zero code edits.
#
# The gate is layered: (1) the pydantic shape of the triple, (2) vocabulary +
# effective domain/range + symmetric mirror, (3) membership in the edge map.
# All three must pass, or the triple is rejected *and the reason is returned*.

_NONEMPTY = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_EDGENAME = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=S.triple_relation_max_len
    ),
]


def _short(uri: str) -> str:
    return uri.rsplit("#", 1)[-1] if "#" in uri else uri.rstrip("/").rsplit("/", 1)[-1]


def build_entity_types(used_classes: list[str]) -> dict[str, type[BaseModel]]:
    """One Pydantic model per DUL class in use (Graphiti custom entity types)."""
    models: dict[str, type[BaseModel]] = {}
    for uri in used_classes:
        name = _short(uri)
        models[name] = create_model(
            f"DUL{name}",
            __config__=ConfigDict(extra="allow"),
            summary=(str, Field(description=f"Summary of this DUL {name}")),
        )
    return models


def build_edge_types(
    used_relations: list[str],
    lineage: dict[str, dict],
    ancestors: dict[str, set[str]],
    map_classes: list[str],
) -> tuple[
    dict[str, type[BaseModel]],
    dict[tuple[str, str], list[str]],
    dict[tuple[str, str], list[str]],
]:
    """One Pydantic model per DUL relation + allowed (subject, object) class maps.

    Returns (edge_models, edge_map_full, edge_map_graphiti). Full-URI keys drive
    the strict gate; short-name keys drive Graphiti's edge_type_map. Both derive
    from the same subclass rule as validation (subject ⊆ all domains,
    object ⊆ all ranges).
    """
    edge_models: dict[str, type[BaseModel]] = {}
    edge_map: dict[tuple[str, str], list[str]] = {}
    for uri in used_relations:
        name = _short(uri)
        lin = lineage.get(uri, {})
        doms = lin.get("domain", [])
        rngs = lin.get("range", [])
        edge_models[name] = create_model(
            f"DUL{name}Edge",
            __config__=ConfigDict(extra="allow"),
            fact=(str, Field(description=f"Fact sentence for this {name} edge")),
        )
        for s in map_classes:
            if not all(is_subclass_of(s, d, ancestors) for d in doms):
                continue
            for o in map_classes:
                if all(is_subclass_of(o, r, ancestors) for r in rngs):
                    edge_map.setdefault((s, o), []).append(name)
    graphiti_map: dict[tuple[str, str], list[str]] = {}
    for (s, o), names in edge_map.items():
        graphiti_map.setdefault((_short(s), _short(o)), []).extend(names)
    for names in graphiti_map.values():
        names[:] = sorted(set(names))
    return edge_models, edge_map, graphiti_map


class ProposedTriple(BaseModel):
    """Exact triple shape the pipeline must emit (model I/O boundary)."""

    model_config = ConfigDict(extra="forbid")

    subject_id: _NONEMPTY = Field(max_length=S.triple_id_max_len)
    subject_name: _NONEMPTY = Field(max_length=S.triple_name_max_len)
    subject_class: _NONEMPTY = Field(description="Full DUL class URI")
    relation: _NONEMPTY = Field(description="Full DUL object-property URI")
    relation_name: _EDGENAME = Field(
        description="Human edge context, distinct from the DOLCE type"
    )
    object_id: _NONEMPTY = Field(max_length=S.triple_id_max_len)
    object_name: _NONEMPTY = Field(max_length=S.triple_name_max_len)
    object_class: _NONEMPTY = Field(description="Full DUL class URI")
    fact_sentence: _NONEMPTY = Field(
        max_length=S.triple_fact_max_len,
        description="One-sentence verbalization for Graphiti ingestion",
    )
    source: _NONEMPTY = Field(max_length=S.triple_source_max_len)


def edge_type_allowed(
    subject_class: str,
    relation: str,
    object_class: str,
    edge_map: dict[tuple[str, str], list[str]],
    ancestors: dict[str, set[str]],
) -> tuple[bool, str]:
    """Second gate layer: is (subj class, relation, obj class) in the edge map?"""
    rel = _short(relation)
    for (d, r), names in edge_map.items():
        if rel not in names:
            continue
        if is_subclass_of(subject_class, d, ancestors) and is_subclass_of(
            object_class, r, ancestors
        ):
            return (
                True,
                (
                    f"OK: {_short(subject_class)} -[{rel}]-> {_short(object_class)} "
                    "allowed by edge_type_map"
                ),
            )
    return False, (
        f"edge_type_map has no ({_short(subject_class)}, {rel}, "
        f"{_short(object_class)}) entry: this triple cannot be created under "
        "strict DUL enforcement"
    )


def dul_gate(
    triple: dict[str, Any],
    schema: dict[str, Any],
    ancestors: dict[str, set[str]],
    lineage: dict[str, dict],
    edge_map: dict[tuple[str, str], list[str]],
) -> tuple[bool, list[str]]:
    """Full gate: pydantic shape + DUL vocab/domain/range/symmetric + edge map."""
    issues: list[str] = []
    try:
        ProposedTriple(**triple)
    except ValidationError as exc:
        return False, [f"schema check failed: {exc}"]
    ok, msg = validate_fact(triple, schema, ancestors, lineage)
    if not ok:
        issues.append(msg)
    map_ok, map_msg = edge_type_allowed(
        triple["subject_class"],
        triple["relation"],
        triple["object_class"],
        edge_map,
        ancestors,
    )
    if not map_ok:
        issues.append(map_msg)
    return (len(issues) == 0), issues


def format_issues_for_retry(issues: list[str], attempt: int) -> str:
    """Human-readable complaint handed back to the model on a retry."""
    return (
        f"Attempt {attempt} rejected by the DUL gate. Fix ALL of these and re-emit "
        f"the triple JSON:\n- " + "\n- ".join(issues)
    )


def gate_diagnosis(
    triple: dict[str, Any],
    ancestors: dict[str, set[str]],
    lineage: dict[str, dict],
) -> dict[str, Any]:
    """Structured verdict of the type constraints (used by the repair loop).

    The gate's message says *what* is wrong; the repair loop needs to know
    *which side* is at fault, so it can ask Jev for a different **class**
    instead of a different **relation**. The verdict is computed from the very
    same domain/range rules the gate applies — it is never parsed out of the
    issue text, so it cannot drift away from the enforcement.

    Keys:

    * `side` — `"subject"`, `"object"`, `"both"` or `""` (the side whose class
      violates the relation's type constraint; empty when the classes are
      fine);
    * `subject_class_bad` / `object_class_bad` — the same, per side;
    * `symmetric_bad` — the mirrored triple would violate the constraint;
    * `domains` / `ranges` — the effective types of the relation;
    * `subject_types` / `object_types` — **the types the class of that side
      has to satisfy** for the relation to be legal. For an asymmetric
      relation these are the domains and the ranges; for a symmetric one the
      mirror makes both ends satisfy *both* sides, so the two lists are the
      same. These lists are what the class repair offers as candidates, so
      every candidate it produces is a class the strict gate accepts for that
      relation.
    """
    rel = str(triple.get("relation", ""))
    sc = str(triple.get("subject_class", ""))
    oc = str(triple.get("object_class", ""))
    lin = lineage.get(rel, {})
    domains = list(lin.get("domain", []))
    ranges = list(lin.get("range", []))
    symmetric = bool(lin.get("symmetric"))

    # The mirror of a symmetric relation swaps the roles of the two ends:
    # the object has to satisfy the domains and the subject the ranges.
    if symmetric:
        subject_types = sorted({*domains, *ranges})
        object_types = sorted({*domains, *ranges})
    else:
        subject_types = list(domains)
        object_types = list(ranges)

    bad_d = [t for t in subject_types if not is_subclass_of(sc, t, ancestors)]
    bad_r = [t for t in object_types if not is_subclass_of(oc, t, ancestors)]
    mirror_bad = symmetric and (
        any(not is_subclass_of(oc, d, ancestors) for d in domains)
        or any(not is_subclass_of(sc, r, ancestors) for r in ranges)
    )

    subject_class_bad = bool(bad_d)
    object_class_bad = bool(bad_r)
    if subject_class_bad and object_class_bad:
        side = "both"
    elif subject_class_bad:
        side = "subject"
    elif object_class_bad:
        side = "object"
    else:
        side = ""
    return {
        "relation": local_name(rel),
        "domains": domains,
        "ranges": ranges,
        "subject_types": subject_types,
        "object_types": object_types,
        "subject_class_bad": subject_class_bad,
        "object_class_bad": object_class_bad,
        "symmetric_bad": mirror_bad,
        "scoped": bool(domains and ranges),
        "side": side,
    }
