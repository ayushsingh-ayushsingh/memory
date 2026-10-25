from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .paths import PROJECT_ROOT
from .settings import S


# %% Cell 07 — DUL SCHEMA SNAPSHOT (offline, no live database)
#
# The database instance the snapshots were extracted from is gone.
# `data/dul_schema.json` is the source of truth for the **strict gate**:
# subclass edges (for the transitive closure), property domain/range edges,
# sub-property edges and the property characteristics.


def build_subclass_ancestors(
    subclass_edges: list[tuple[str, str]],
) -> dict[str, set[str]]:
    """Transitive closure of named SCO edges: class -> {self + ancestors}."""
    parents: dict[str, set[str]] = {}
    for child, parent in subclass_edges:
        parents.setdefault(child, set()).add(parent)
        parents.setdefault(parent, set())
    result: dict[str, set[str]] = {}
    for cls in list(parents):
        seen: set[str] = set()
        stack = list(parents.get(cls, set()))
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(parents.get(node, set()) - seen)
        result[cls] = seen | {cls}
    return result


def build_property_lineage(schema: dict[str, Any]) -> dict[str, dict]:
    """Effective domain/range per property incl. superproperty (SPO) chain."""
    dom_map: dict[str, set[str]] = defaultdict(set)
    for prop, dom in schema["domain_edges"]:
        dom_map[prop].add(dom)
    rng_map: dict[str, set[str]] = defaultdict(set)
    for prop, rng in schema["range_edges"]:
        rng_map[prop].add(rng)
    super_map: dict[str, set[str]] = defaultdict(set)
    for sub, sup in schema["subproperty_edges"]:
        super_map[sub].add(sup)

    char_map: dict[str, set[str]] = defaultdict(set)
    for prop, char in schema.get("characteristics", []):
        char_map[prop].add(char)

    lineage: dict[str, dict] = {}
    for prop in schema["object_properties"]:
        eff_dom: set[str] = set()
        eff_rng: set[str] = set()
        supers: set[str] = set()
        stack = [prop]
        visited: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            eff_dom |= dom_map.get(cur, set())
            eff_rng |= rng_map.get(cur, set())
            for sup in super_map.get(cur, set()):
                supers.add(sup)
                stack.append(sup)
        flags = char_map.get(prop, set())
        lineage[prop] = {
            "domain": sorted(eff_dom),
            "range": sorted(eff_rng),
            "superproperties": sorted(supers),
            "symmetric": "Symmetric" in flags,
            "transitive": "Transitive" in flags,
            "characteristics": sorted(flags),
        }
    return lineage


def is_subclass_of(child: str, parent: str, ancestors: dict[str, set[str]]) -> bool:
    """Subclass test over the transitive closure (identity included)."""
    if child == parent:
        return True
    return parent in ancestors.get(child, {child})


def load_schema(
    root: Path | str | None = None,
) -> tuple[dict[str, Any], dict[str, set[str]], dict[str, dict]]:
    """Load data/dul_schema.json; rebuild sets; refresh lineage; no connections."""
    base = PROJECT_ROOT / S.data_dir if root is None else Path(root)
    schema_path = base / "dul_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # JSON stores edges as lists; restore tuple form for the builders.
    for key in ("subclass_edges", "subproperty_edges", "domain_edges", "range_edges"):
        schema[key] = [tuple(e) for e in schema.get(key, [])]
    schema["characteristics"] = [tuple(e) for e in schema.get("characteristics", [])]
    ancestors = build_subclass_ancestors(schema["subclass_edges"])
    lineage = build_property_lineage(schema)
    schema["property_lineage"] = lineage
    schema["subclass_ancestors"] = {k: sorted(v) for k, v in ancestors.items()}
    sym = sum(1 for lin in lineage.values() if lin.get("symmetric"))
    tra = sum(1 for lin in lineage.values() if lin.get("transitive"))
    print(
        f"DUL snapshots: {len(schema['classes'])} classes, "
        f"{len(schema['object_properties'])} object properties, "
        f"{sym} symmetric, {tra} transitive "
        f"(offline, from {schema_path.name})"
    )
    return schema, ancestors, lineage
