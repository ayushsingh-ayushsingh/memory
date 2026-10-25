from __future__ import annotations

import json
from typing import Any

from .deps import get_jev_deps
from .extraction import (
    ExtractionResult,
    GateRow,
    MappingResult,
    MappedTriple,
    PairRelation,
    UnmappedPair,
    extract_entities_relations,
    humanize,
    slugify,
)
from .gate import (
    ProposedTriple,
    dul_gate,
    gate_diagnosis,
)
from .jev import JevClient, build_choice
from .mapper import OntologyMapper
from .mapper_types import (
    ClassMapping,
    ClassRepairRequest,
    PropertyMapping,
    pair_key,
)
from .settings import Settings, get_settings


# %% Stage 2 — Jev maps the entity pairs onto surface relations


async def map_pair_relations(
    client: JevClient,
    text: str,
    entities: list[str],
    relations: list[str],
    settings: Settings | None = None,
) -> list[PairRelation]:
    """Ask Jev which relation holds between every pair of entities.

    Every pair is asked **in both directions** and every question of the run
    travels in a single request, so the whole relation mapping costs one
    round trip.
    """
    s = settings or get_settings()
    none_label = s.jev_none_option_key
    options = {relation: humanize(relation) for relation in relations}
    if s.jev_include_none_option:
        options[none_label] = (
            "None of the listed relations holds between these two entities."
        )
    if not options:
        return []

    state = json.dumps({"text_chunk": text, "entities": entities})
    questions: dict[str, Any] = {}
    plan: list[tuple[str, str, str, str]] = []
    pairs = [
        (entities[i], entities[j])
        for i in range(len(entities))
        for j in range(i + 1, len(entities))
    ]
    # Safety valve: the probe is quadratic in the number of entities.
    pairs = pairs[: max(1, s.jev_max_pairs)]
    for subject, obj in pairs:
        for direction, first, second in (
            ("forward", subject, obj),
            ("reverse", obj, subject),
        ):
            if direction == "reverse" and not s.jev_probe_both_directions:
                continue
            qid = f"rel::{subject}::{obj}::{direction}"
            questions[qid] = build_choice(
                (
                    f"According to the text, does one of these relations hold "
                    f"from '{first}' to '{second}' — that is, is '{first}' the "
                    f"entity the relation is about and '{second}' the one it "
                    "points to? Choose a relation only when the text states it "
                    "in this direction; choose the none-option otherwise, "
                    "including when the text states the opposite direction."
                ),
                options,
                s.jev_max_choices,
            )
            plan.append((qid, first, second, direction))

    if not questions:
        return []
    answers = await client.ask_batched(questions, state)

    rows: list[PairRelation] = []
    forward: dict[tuple[str, str], PairRelation] = {}
    for qid, first, second, direction in plan:
        answer = answers.get(qid)
        if answer is None or answer.choice == none_label:
            continue
        if answer.confidence < s.jev_min_pair_confidence:
            continue
        row = PairRelation(
            subject=first,
            relation=answer.choice,
            object=second,
            direction=direction,
            confidence=round(float(answer.confidence), 4),
            probabilities=dict(answer.probabilities),
        )
        if direction == "forward":
            forward[(first, second)] = row
            rows.append(row)
        else:
            # The reverse direction only adds information when it names a
            # *different* relation — otherwise it would duplicate the forward
            # fact with the direction flipped.
            existing = forward.get((second, first))
            if existing is None or existing.relation != row.relation:
                rows.append(row)
    return rows


# %% Stage 3 — triples


def _node_id(name: str) -> str:
    return slugify(name)


def build_triples(
    pairs: list[PairRelation],
    class_map: dict[str, ClassMapping],
    property_map: dict[str, PropertyMapping],
    source: str | None = None,
    settings: Settings | None = None,
) -> list[MappedTriple]:
    """Assemble the DUL triples from the three mappings."""
    s = settings or get_settings()
    source = source or s.jev_source_label
    out: list[MappedTriple] = []
    seen: set[str] = set()
    for pair in pairs:
        subject_class = class_map.get(pair.subject)
        object_class = class_map.get(pair.object)
        if subject_class is None or object_class is None:
            continue
        if not subject_class.decided or not object_class.decided:
            continue
        key = pair_key(pair.subject, pair.relation, pair.object)
        mapping = property_map.get(key)
        if mapping is None or not mapping.decided:
            continue
        fact_key = f"{_node_id(pair.subject)}|{mapping.property_name}|{_node_id(pair.object)}"
        if fact_key in seen:
            continue
        seen.add(fact_key)
        triple = ProposedTriple(
            subject_id=_node_id(pair.subject),
            subject_name=pair.subject,
            subject_class=subject_class.class_uri,
            relation=mapping.property_uri,
            relation_name=humanize(pair.relation),
            object_id=_node_id(pair.object),
            object_name=pair.object,
            object_class=object_class.class_uri,
            fact_sentence=(
                f"{pair.subject} {humanize(pair.relation)} {pair.object}."
            ),
            source=source,
        )
        out.append(
            MappedTriple(
                triple=triple,
                pair_key=key,
                surface_relation=pair.relation,
                pair_confidence=pair.confidence,
                class_confidence=min(
                    subject_class.confidence, object_class.confidence
                ),
                property_confidence=mapping.confidence,
                property_tier=mapping.tier,
                subject_class_name=subject_class.class_name,
                object_class_name=object_class.class_name,
            )
        )
    return out


# %% Stage 4 — the strict gate


def validate_triples(
    triples: list[MappedTriple], deps: dict[str, Any]
) -> list[GateRow]:
    """Run the strict DUL gate over every triple."""
    rows: list[GateRow] = []
    for item in triples:
        triple = item.triple
        ok, issues = dul_gate(
            triple.model_dump(),
            deps["schema"],
            deps["ancestors"],
            deps["lineage"],
            deps["edge_map"],
        )
        item.gate_ok = ok
        item.gate_issues = list(issues)
        rows.append(
            GateRow(
                subject=f"{triple.subject_name} ({item.subject_class_name})",
                subject_class=triple.subject_class,
                relation=triple.relation.rsplit("#", 1)[-1],
                relation_name=triple.relation_name,
                object=f"{triple.object_name} ({item.object_class_name})",
                object_class=triple.object_class,
                valid=ok,
                detail="; ".join(issues) if issues else "gate passed",
            )
        )
    return rows


# %% Stage 5 — the mapping stage with the strict retry loop


def _class_repair_requests(
    item: MappedTriple,
    deps: dict[str, Any],
    complaint: str,
    exclude_classes: dict[str, set[str]],
) -> list[ClassRepairRequest]:
    """The class repairs a rejected triple asks for (none when classes are fine).

    The types the new class has to satisfy come from `gate_diagnosis`, which
    applies the gate's own domain/range rule — so every class Jev can pick is
    one the gate accepts for the rejected relation. The rejected class is
    recorded in `exclude_classes` so a later round cannot propose it again
    (that would be the ping-pong the retry budget exists to stop).
    """
    triple = item.triple
    diagnosis = gate_diagnosis(
        triple.model_dump(), deps["ancestors"], deps["lineage"]
    )
    if not diagnosis["scoped"]:
        return []
    _subject, _surface, obj = item.pair_key.split("|", 2)
    sides = (
        (
            "subject",
            triple.subject_name,
            triple.subject_class,
            diagnosis["subject_types"],
            diagnosis["subject_class_bad"],
        ),
        (
            "object",
            obj,
            triple.object_class,
            diagnosis["object_types"],
            diagnosis["object_class_bad"],
        ),
    )
    out: list[ClassRepairRequest] = []
    for side, entity, rejected, types, bad in sides:
        if not bad:
            continue
        exclude_classes.setdefault(entity, set()).add(rejected)
        out.append(
            ClassRepairRequest(
                entity=entity,
                side=side,
                rejected_class=rejected,
                relation=triple.relation,
                types=list(types),
                complaint=complaint,
            )
        )
    return out


def _restore_original_relations(
    failing: list[MappedTriple],
    class_map: dict[str, ClassMapping],
    property_map: dict[str, PropertyMapping],
    originals: dict[str, PropertyMapping],
    deps: dict[str, Any],
) -> list[str]:
    """Prefer Jev's *first* relation when a class repair makes it legal.

    The property re-ask of a repair round is influenced by the failure (the
    rejected relation is excluded), while the first answer was not. If the
    repaired classes now satisfy the original relation, restoring it keeps
    the most honest reading of the text. A pair whose classes did not change
    is left alone: its original relation was already rejected and the re-ask
    exists precisely to replace it.
    """
    restored: list[str] = []
    for item in failing:
        key = item.pair_key
        original = originals.get(key)
        current = property_map.get(key)
        if original is None or current is None or not original.decided:
            continue
        if original.property_uri == current.property_uri:
            continue
        subject, _surface, obj = key.split("|", 2)
        subject_class = class_map.get(subject)
        object_class = class_map.get(obj)
        if subject_class is None or object_class is None:
            continue
        if not subject_class.decided or not object_class.decided:
            continue
        if (
            subject_class.class_uri == item.triple.subject_class
            and object_class.class_uri == item.triple.object_class
        ):
            continue
        trial = item.triple.model_dump()
        trial.update(
            {
                "subject_name": subject,
                "subject_class": subject_class.class_uri,
                "relation": original.property_uri,
                "object_name": obj,
                "object_class": object_class.class_uri,
            }
        )
        ok, _issues = dul_gate(
            trial,
            deps["schema"],
            deps["ancestors"],
            deps["lineage"],
            deps["edge_map"],
        )
        if not ok:
            continue
        property_map[key] = original
        restored.append(key)
    return restored


def _unmapped_pairs(
    pairs: list[PairRelation],
    class_map: dict[str, ClassMapping],
    property_map: dict[str, PropertyMapping],
    triples: list[MappedTriple],
) -> list[UnmappedPair]:
    """Surface pairs that produced no triple at all, with the blocking stage."""
    mapped = {item.pair_key for item in triples}
    out: list[UnmappedPair] = []
    for pair in pairs:
        key = pair_key(pair.subject, pair.relation, pair.object)
        if key in mapped:
            continue
        subject_class = class_map.get(pair.subject)
        object_class = class_map.get(pair.object)
        if subject_class is None or object_class is None:
            reason = "entity missing from the class mapping"
        elif not subject_class.decided or not object_class.decided:
            reason = "class mapping undecided"
        else:
            mapping = property_map.get(key)
            reason = (
                "property mapping undecided"
                if mapping is None or not mapping.decided
                else "duplicate of an already mapped fact"
            )
        out.append(
            UnmappedPair(
                subject=pair.subject,
                relation=pair.relation,
                object=pair.object,
                reason=reason,
            )
        )
    return out


async def map_ontology(
    client: JevClient,
    text: str,
    extraction: ExtractionResult,
    deps: dict[str, Any],
    settings: Settings | None = None,
) -> MappingResult:
    """Map a text chunk onto the ontology and gate the result.

    The retry loop is the point of this function: when the gate rejects a
    triple, the repair round re-asks Jev with *different* choices in a single
    batched request — the gate's own complaint in the instructions, the
    rejected relation excluded, and (when the classes are at fault) a class
    repair whose candidates are exactly the classes that satisfy the rejected
    relation's type constraint.

    The re-ask of the relation and the repair of the class travel together,
    so one rejection costs one round trip; if the repaired class makes the
    *original* relation legal again, that relation is restored (it was Jev's
    clean, unbiased answer) and only otherwise is the re-asked relation used.
    """
    s = settings or get_settings()
    mapper = OntologyMapper(client, settings=s)
    state = json.dumps(
        {
            "text_chunk": text,
            "entities": extraction.entities,
            "relations": extraction.relations,
        }
    )

    pairs = await map_pair_relations(
        client, text, extraction.entities, extraction.relations, s
    )
    class_map = await mapper.map_classes(extraction.entities, state)

    def _requests() -> list[tuple[str, str, str, str, str]]:
        out: list[tuple[str, str, str, str, str]] = []
        for pair in pairs:
            subject_class = class_map.get(pair.subject)
            object_class = class_map.get(pair.object)
            if subject_class is None or object_class is None:
                continue
            if not subject_class.decided or not object_class.decided:
                continue
            out.append(
                (
                    pair.subject,
                    subject_class.class_uri,
                    pair.relation,
                    pair.object,
                    object_class.class_uri,
                )
            )
        return out

    requests = _requests()
    property_map = await mapper.map_properties(requests, state)
    first_property_map = dict(property_map)

    exclude: dict[str, set[str]] = {}
    exclude_classes: dict[str, set[str]] = {}
    notes: dict[str, str] = {}
    triples: list[MappedTriple] = []
    gate_rows: list[GateRow] = []
    retries = 0
    result_notes: list[str] = []

    for attempt in range(s.jev_mapping_retries + 1):
        triples = build_triples(pairs, class_map, property_map, settings=s)
        gate_rows = validate_triples(triples, deps)

        failing = [item for item in triples if not item.gate_ok]
        if not failing:
            break
        if attempt >= s.jev_mapping_retries:
            result_notes.append(
                f"{len(failing)} triple(s) still rejected after "
                f"{retries} retry round(s): "
                + "; ".join(
                    f"{item.pair_key} -> {', '.join(item.gate_issues)}"
                    for item in failing
                )
            )
            break

        retries += 1
        failing_keys: set[str] = set()
        class_requests: list[ClassRepairRequest] = []
        for item in failing:
            key = item.pair_key
            failing_keys.add(key)
            exclude.setdefault(key, set()).add(item.triple.relation)
            previous = notes.get(key, "")
            issue = "; ".join(item.gate_issues)
            notes[key] = f"{previous}; {issue}".strip("; ") if previous else issue
            class_requests.extend(
                _class_repair_requests(item, deps, issue, exclude_classes)
            )

        retry_requests = [
            request
            for request in _requests()
            if pair_key(request[0], request[2], request[3]) in failing_keys
        ]
        result_notes.append(
            f"retry {retries}: {len(failing_keys)} rejected triple(s) re-mapped "
            f"with {sum(len(v) for v in exclude.values())} excluded candidate(s) "
            f"and {len(class_requests)} class repair(s)"
        )
        if not retry_requests:
            break

        repaired_classes, repaired = await mapper.repair_round(
            retry_requests,
            state,
            deps,
            exclude=exclude,
            notes=notes,
            class_requests=class_requests,
            exclude_classes=exclude_classes,
        )
        class_map.update(repaired_classes)
        property_map.update(repaired)
        restored = _restore_original_relations(
            failing, class_map, property_map, first_property_map, deps
        )
        if restored:
            result_notes.append(
                f"retry {retries}: restored the original relation of "
                f"{len(restored)} pair(s) after the class repair made it legal"
            )

    unmapped = _unmapped_pairs(pairs, class_map, property_map, triples)
    result_notes.extend(
        f"{key}: {mapping.note}"
        for key, mapping in sorted(property_map.items())
        if mapping.note
    )
    result_notes.extend(
        f"unmapped {pair.subject} -[{pair.relation}]-> {pair.object}: {pair.reason}"
        for pair in unmapped
    )

    return MappingResult(
        extraction=extraction,
        pair_relations=pairs,
        class_mappings=class_map,
        property_mappings=property_map,
        triples=triples,
        gate_rows=gate_rows,
        unmapped=unmapped,
        retries=retries,
        usage=client.usage.model_copy(),
        notes=result_notes,
    )


# %% Orchestration


async def map_text(
    text: str,
    client: JevClient,
    deps: dict[str, Any] | None = None,
    extraction: ExtractionResult | None = None,
    settings: Settings | None = None,
) -> MappingResult:
    """Run the whole mapping pipeline (no writes)."""

    s = settings or get_settings()
    extraction = extraction or await extract_entities_relations(text, s)
    return await map_ontology(
        client, text, extraction, deps or get_jev_deps(), s
    )
