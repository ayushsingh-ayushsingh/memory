from __future__ import annotations

import json
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from .paths import PROJECT_ROOT
from .settings import S


# %% Cell 08 — DUL ONTOLOGY from the database export (`graph.json`)
#
# The export is the **source of truth** for the class hierarchy and the
# object properties: it is the only artefact that carries the SCO / SPO /
# DOMAIN / RANGE edges exactly as the ontology engine stored them, together
# with the human-readable comments the Jev mapper needs as option
# descriptions. The loader reproduces the parse semantics of `dolce_tree.py`
# and self-checks the counts it derives (see the SELFCHECK cell), so a
# changed or truncated export fails loudly instead of silently producing a
# half-empty ontology.

Kind = Literal["class", "objprop", "dataprop", "other"]


# %% Parse helpers (mirrors of dolce_tree.py — same parse semantics)


def local_name(uri: str) -> str:
    """`http://...#Foo` -> `Foo`."""
    return uri.rsplit("#", 1)[-1] if "#" in uri else uri.rstrip("/").rsplit("/", 1)[-1]


def _record_fields(rec: Any) -> list[Any]:
    """Graph-database driver record snapshots may carry `_fields` or `keys`."""
    if isinstance(rec, dict) and "_fields" in rec:
        return rec["_fields"]
    if isinstance(rec, dict) and rec.get("keys"):
        return [rec.get(k) for k in rec["keys"]]
    if isinstance(rec, dict):
        return list(rec.values())
    return []


def _nid(obj: dict[str, Any]) -> str:
    """Stable node identity (element id, falling back to the internal id)."""
    return obj.get("elementId") or str(obj["identity"]["low"])


def _node_kind(labels: list[str]) -> Kind:
    """Class / Relationship / Property / anything else."""
    ls = {label.split("__")[-1] for label in labels}
    if "Class" in ls:
        return "class"
    if "Relationship" in ls:
        return "objprop"
    if "Property" in ls:
        return "dataprop"
    return "other"


def _ends(rel: dict[str, Any]) -> tuple[str, str]:
    start = rel.get("startNodeElementId") or str(rel["start"]["low"])
    end = rel.get("endNodeElementId") or str(rel["end"]["low"])
    return start, end


# %% Ontology models


class OntologyTerm(BaseModel):
    """One node of the ontology export."""

    model_config = ConfigDict(extra="forbid")

    uri: str
    name: str
    kind: Kind
    label: str = ""
    comment: str = ""


class OntologyProperty(BaseModel):
    """An object property with its effective domain/range.

    `domain` / `range` are the **effective** ones (own edges plus everything
    inherited through `subPropertyOf`) — they are what the strict gate
    enforces. `own_domain` / `own_range` are the edges the export declares
    for this property alone; they are *narrower* and therefore a much better
    signal of how specific the relation is (a property declared
    `Object -> Role` says far more than one that merely inherits
    `Entity -> Entity`).
    """

    model_config = ConfigDict(extra="forbid")

    uri: str
    name: str
    comment: str = ""
    superproperties: list[str] = Field(default_factory=list)
    subproperties: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    range: list[str] = Field(default_factory=list)
    own_domain: list[str] = Field(default_factory=list)
    own_range: list[str] = Field(default_factory=list)
    characteristics: list[str] = Field(default_factory=list)

    @property
    def symmetric(self) -> bool:
        return "Symmetric" in self.characteristics

    @property
    def transitive(self) -> bool:
        return "Transitive" in self.characteristics

    def describe(self, max_chars: int) -> str:
        """Option text for a Jev criterion: name + (trimmed) definition.

        The effective domain/range is appended: it is what makes an
        admissible relation distinguishable from an inadmissible one, and it
        is read straight off the ontology export.
        """
        scope = self.scope()
        if not self.comment:
            return scope or self.name
        comment = self.comment
        if len(comment) > max_chars:
            comment = comment[: max_chars - 1].rstrip() + "…"
        return f"{self.name}: {comment}" + (f" ({scope})" if scope else "")

    def scope(self) -> str:
        """`domain: X, Y; range: Z` built from the effective types."""
        names = [local_name(u) for u in self.domain]
        ranges = [local_name(u) for u in self.range]
        if not names and not ranges:
            return ""
        return (
            "domain: "
            + (", ".join(names) or "-")
            + "; range: "
            + (", ".join(ranges) or "-")
        )


class Ontology(BaseModel):
    """The parsed DUL ontology."""

    model_config = ConfigDict(extra="forbid")

    classes: dict[str, OntologyTerm] = Field(default_factory=dict)
    object_properties: dict[str, OntologyProperty] = Field(default_factory=dict)
    data_properties: dict[str, OntologyTerm] = Field(default_factory=dict)
    other_terms: dict[str, OntologyTerm] = Field(default_factory=dict)
    class_children: dict[str, list[str]] = Field(default_factory=dict)
    class_parents: dict[str, list[str]] = Field(default_factory=dict)
    class_ancestors: dict[str, list[str]] = Field(default_factory=dict)
    class_depth: dict[str, int] = Field(default_factory=dict)
    root_class: str = ""
    counts: dict[str, int] = Field(default_factory=dict)

    # %% Class helpers
    def children_of(self, uri: str) -> list[str]:
        """Direct subclasses (empty for leaves)."""
        return self.class_children.get(uri, [])

    def parents_of(self, uri: str) -> list[str]:
        return self.class_parents.get(uri, [])

    def ancestors_of(self, uri: str) -> set[str]:
        """The class itself plus every transitive superclass."""
        return set(self.class_ancestors.get(uri, [uri]))

    def is_subclass(self, child: str, parent: str) -> bool:
        if child == parent:
            return True
        return parent in self.ancestors_of(child)

    def depth_of(self, uri: str) -> int:
        """How deep the class sits in the hierarchy (root = 0).

        A class with several parents (the export has nine of them) takes the
        *deepest* path: that is the path along which it is most specific.
        """
        return self.class_depth.get(uri, 0)

    def type_specificity(self, actual: str, declared: list[str]) -> int:
        """How specific a declared type is for the class that must satisfy it.

        `actual` is the class of the triple, `declared` the types a property
        declares for that side. The result is the depth of the **most
        specific** declared type that still admits `actual`:

        * a property declared `Entity -> Entity` scores 0 — it says nothing
          about the classes involved;
        * a property declared `Agent -> SocialAgent` scores the depth of
          `Agent` / `SocialAgent` — it was written for exactly this kind of
          class and therefore carries the meaning.

        This is the signal that separates a *typed* DUL relation from the
        generic catch-alls, without hardcoding a single relation name.
        """
        best = -1
        for declared_uri in declared:
            if self.is_subclass(actual, declared_uri):
                best = max(best, self.depth_of(declared_uri))
        return best

    def class_name(self, uri: str) -> str:
        term = self.classes.get(uri)
        return term.name if term else local_name(uri)

    def find_class(self, name: str) -> str | None:
        """Resolve a class by its short name (case-insensitive)."""
        target = name.strip().lower()
        for uri, term in self.classes.items():
            if term.name.lower() == target:
                return uri
        return None

    # %% Property helpers
    def property_name(self, uri: str) -> str:
        prop = self.object_properties.get(uri)
        return prop.name if prop else local_name(uri)

    def compatible_properties(self, subject_class: str, object_class: str) -> list[str]:
        """Object properties whose effective domain/range admit the class pair.

        The rule is deliberately the *strict* one used by the gate: the
        subject must be a subclass of **every** declared domain and the object
        of **every** declared range. Symmetric properties additionally have to
        admit the mirrored triple, otherwise the gate would reject the result
        later on.
        """
        out: list[str] = []
        for uri, prop in self.object_properties.items():
            if not prop.domain or not prop.range:
                continue
            if not all(self.is_subclass(subject_class, d) for d in prop.domain):
                continue
            if not all(self.is_subclass(object_class, r) for r in prop.range):
                continue
            if prop.symmetric and not (
                all(self.is_subclass(object_class, d) for d in prop.domain)
                and all(self.is_subclass(subject_class, r) for r in prop.range)
            ):
                continue
            out.append(uri)
        return out

    def relaxed_properties(self, subject_class: str, object_class: str) -> list[str]:
        """Near-miss properties: exactly one side of the type constraint fits.

        These are **not** gate-valid — the gate rejects them and says why.
        They exist so the mapper can offer the semantically right relation
        when DUL has no strictly typed one for the class pair: the gate then
        rejects the pick, the retry excludes it and re-asks with the gate's
        own complaint, which is what turns a hard failure into a usable
        triple.
        """
        out: list[str] = []
        for uri, prop in self.object_properties.items():
            if not prop.domain or not prop.range:
                continue
            domain_ok = all(self.is_subclass(subject_class, d) for d in prop.domain)
            range_ok = all(self.is_subclass(object_class, r) for r in prop.range)
            if domain_ok == range_ok:
                continue
            if prop.symmetric and not (
                all(self.is_subclass(object_class, d) for d in prop.domain)
                and all(self.is_subclass(subject_class, r) for r in prop.range)
            ):
                continue
            out.append(uri)
        return out

    def specificity_tier(self, uri: str) -> int:
        """0 = fully typed, 3 = fully generic (Entity -> Entity).

        The tier drives the order in which candidate properties are offered to
        Jev: the typed relations carry far more meaning than the catch-all
        ones, so they are tried first.
        """
        prop = self.object_properties.get(uri)
        if prop is None:
            return 3
        root = self.root_class
        typed_domain = not (set(prop.domain) == {root})
        typed_range = not (set(prop.range) == {root})
        if typed_domain and typed_range:
            return 0
        if typed_domain:
            return 1
        if typed_range:
            return 2
        return 3


# %% Ontology loader


def _load_characteristics(path: Path) -> dict[str, set[str]]:
    """`{property_uri: {"Symmetric", "Transitive"}}` from the side-car file.

    Two shapes are supported: a `detail` list of
    `{"property": uri, "characteristics": [...]}` records and the flat
    `symmetric` / `transitive` URI lists.
    """
    characteristics: dict[str, set[str]] = defaultdict(set)
    if not path.exists():
        return characteristics
    raw = json.loads(path.read_text(encoding="utf-8"))
    detail = raw.get("detail")
    if isinstance(detail, list):
        for row in detail:
            uri = row.get("property")
            if not uri:
                continue
            characteristics[uri].update(row.get("characteristics", []))
        return characteristics
    for flag, values in raw.items():
        if not isinstance(values, list):
            continue
        for uri in values:
            if isinstance(uri, str):
                characteristics[uri].add(flag.capitalize())
    return characteristics


def _parse_export(records: list[Any]) -> tuple[dict[str, OntologyTerm], dict[str, Any]]:
    """Split the export into terms and relationships."""
    terms: dict[str, OntologyTerm] = {}
    relationships: dict[str, Any] = {}
    for rec in records:
        for obj in _record_fields(rec):
            if not isinstance(obj, dict):
                continue
            if "labels" in obj:
                props = obj.get("properties", {}) or {}
                uri = props.get("uri", "")
                name = props.get("n4sch__name") or local_name(uri)
                comment = " ".join((props.get("n4sch__comment", "") or "").split())
                terms[_nid(obj)] = OntologyTerm(
                    uri=uri,
                    name=name,
                    kind=_node_kind(obj["labels"]),
                    label=props.get("n4sch__label", "") or "",
                    comment=comment,
                )
            elif "type" in obj:
                relationships[_nid(obj)] = obj
    return terms, relationships


def load_ontology(
    path: Path | str | None = None,
    characteristics_path: Path | str | None = None,
) -> Ontology:
    """Parse the export into an `Ontology` (no network, no hardcoded names)."""
    base = PROJECT_ROOT / S.data_dir
    graph_path = (
        Path(path)
        if path is not None
        else PROJECT_ROOT / S.ontology_graph_path
    )
    if not graph_path.is_absolute():
        graph_path = PROJECT_ROOT / graph_path
    chars_path = (
        Path(characteristics_path)
        if characteristics_path is not None
        else base / S.ontology_characteristics_path
    )
    if not chars_path.is_absolute():
        chars_path = base / chars_path

    records = json.loads(graph_path.read_text(encoding="utf-8"))
    terms, relationships = _parse_export(records)

    classes: dict[str, OntologyTerm] = {}
    object_properties: dict[str, OntologyTerm] = {}
    data_properties: dict[str, OntologyTerm] = {}
    other_terms: dict[str, OntologyTerm] = {}
    for term in terms.values():
        if term.kind == "class":
            classes[term.uri] = term
        elif term.kind == "objprop":
            object_properties[term.uri] = term
        elif term.kind == "dataprop":
            data_properties[term.uri] = term
        else:
            other_terms[term.uri] = term

    # %% Edges
    class_children: dict[str, set[str]] = defaultdict(set)
    class_parents: dict[str, set[str]] = defaultdict(set)
    property_parents: dict[str, set[str]] = defaultdict(set)
    property_children: dict[str, set[str]] = defaultdict(set)
    domain_edges: dict[str, set[str]] = defaultdict(set)
    range_edges: dict[str, set[str]] = defaultdict(set)
    edge_types: Counter[str] = Counter()

    for rel in relationships.values():
        edge_types[rel["type"].split("__")[-1]] += 1
        start, end = _ends(rel)
        if start not in terms or end not in terms:
            continue
        s_term, e_term = terms[start], terms[end]
        kind = rel["type"].split("__")[-1]
        if kind == "SCO" and s_term.kind == "class" and e_term.kind == "class":
            class_children[e_term.uri].add(s_term.uri)
            class_parents[s_term.uri].add(e_term.uri)
        elif kind == "SPO" and s_term.kind == "objprop" and e_term.kind == "objprop":
            property_parents[s_term.uri].add(e_term.uri)
            property_children[e_term.uri].add(s_term.uri)
        elif kind == "DOMAIN" and s_term.kind == "objprop" and e_term.kind == "class":
            domain_edges[s_term.uri].add(e_term.uri)
        elif kind == "RANGE" and s_term.kind == "objprop" and e_term.kind == "class":
            range_edges[s_term.uri].add(e_term.uri)

    # %% Transitive subclass closure
    ancestors: dict[str, set[str]] = {}
    for cls in classes:
        seen: set[str] = set()
        stack = list(class_parents.get(cls, set()))
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(class_parents.get(node, set()) - seen)
        ancestors[cls] = seen | {cls}

    root_candidates = [
        uri for uri, term in classes.items() if term.name == S.ontology_root_class
    ]
    root_class = root_candidates[0] if root_candidates else ""

    # %% Depth of every class (deepest path wins for multi-parent classes)
    depth: dict[str, int] = {uri: 0 for uri in classes}
    for _ in range(len(classes) + 1):
        changed = False
        for cls, parents in class_parents.items():
            candidate = 1 + max((depth[p] for p in parents), default=0)
            if candidate > depth[cls]:
                depth[cls] = candidate
                changed = True
        if not changed:
            break

    # %% Effective domain/range (own edges + everything inherited via SPO)
    characteristics = _load_characteristics(chars_path)
    properties: dict[str, OntologyProperty] = {}
    for uri, term in object_properties.items():
        eff_domain: set[str] = set()
        eff_range: set[str] = set()
        supers: set[str] = set()
        stack = [uri]
        visited: set[str] = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            eff_domain |= domain_edges.get(current, set())
            eff_range |= range_edges.get(current, set())
            for sup in property_parents.get(current, set()):
                supers.add(sup)
                stack.append(sup)
        properties[uri] = OntologyProperty(
            uri=uri,
            name=term.name,
            comment=term.comment,
            superproperties=sorted(supers),
            subproperties=sorted(property_children.get(uri, set())),
            domain=sorted(eff_domain),
            range=sorted(eff_range),
            own_domain=sorted(domain_edges.get(uri, set())),
            own_range=sorted(range_edges.get(uri, set())),
            characteristics=sorted(characteristics.get(uri, set())),
        )

    return Ontology(
        classes=classes,
        object_properties=properties,
        data_properties=data_properties,
        other_terms=other_terms,
        class_children={k: sorted(v) for k, v in class_children.items()},
        class_parents={k: sorted(v) for k, v in class_parents.items()},
        class_ancestors={k: sorted(v) for k, v in ancestors.items()},
        class_depth=depth,
        root_class=root_class,
        counts={
            "records": len(records),
            "classes": len(classes),
            "object_properties": len(properties),
            "data_properties": len(data_properties),
            "other": len(other_terms),
            **{f"edge_{k.lower()}": v for k, v in edge_types.items()},
        },
    )


@lru_cache(maxsize=1)
def get_ontology() -> Ontology:
    """Process-wide ontology singleton (the export is parsed once)."""
    return load_ontology()


def self_check(ontology: Ontology | None = None) -> dict[str, Any]:
    """Compare the parsed export against the recorded snapshot numbers.

    The export is a checked-in artefact: if it is replaced by a partial dump
    the mapper must fail loudly instead of quietly mapping onto half of DUL.
    These counts are verified from the source and must not change.
    """
    onto = ontology or get_ontology()
    expected = {
        "records": 478,
        "classes": 77,
        "object_properties": 112,
        "data_properties": 5,
        "other": 1,
    }
    mismatches = {
        key: {"expected": value, "actual": onto.counts.get(key)}
        for key, value in expected.items()
        if onto.counts.get(key) != value
    }
    return {
        "ok": not mismatches,
        "expected": expected,
        "actual": onto.counts,
        "mismatches": mismatches,
    }
