from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from .jev import JevAnswer


# %% Cell 17 — JEV ONTOLOGY MAPPER (classes + properties, windows everywhere)
#
# Two mappings live here, and **both** are done by Jev (never by the LLM):
#
# 1. `map_classes` — which DOLCE class is an extracted entity?  The class
#    hierarchy is traversed as a depth-synchronous beam search: every level of
#    the tree is one batched request asking, for every entity still on the beam,
#    "which subclass of *parent* is this entity?". Paths are ranked by the
#    geometric mean of their edge probabilities.
#
# 2. `map_properties` — which DUL object property expresses a relation?
#    Candidates are derived from the ontology (subject subclass of every declared
#    domain, object subclass of every declared range — exactly the rule the strict
#    gate applies later) and handed to Jev in windows of at most
#    `jev_max_choices` options.
#
# Cost discipline: every question of every stage travels in one request per
# round, so round trips scale with the *depth* of the ontology, not with the
# number of entities or relations.

# %% Models


class ClassMapping(BaseModel):
    """Entity -> DOLCE class."""

    model_config = ConfigDict(extra="forbid")

    entity: str
    class_uri: str = ""
    class_name: str = ""
    confidence: float = 0.0
    path: list[str] = Field(default_factory=list)
    path_score: float = 0.0
    levels: int = 0
    decided: bool = False
    note: str = ""


class PropertyMapping(BaseModel):
    """Relation -> DOLCE object property."""

    model_config = ConfigDict(extra="forbid")

    subject: str
    relation: str
    object: str
    property_uri: str = ""
    property_name: str = ""
    confidence: float = 0.0
    tier: int = 3
    window: int = 0
    # `candidates` are the relations the strict gate would accept; the
    # `relaxed_candidates` are the near misses (one side of the type
    # constraint does not fit) that are only offered as a fallback.
    candidates: list[str] = Field(default_factory=list)
    relaxed_candidates: list[str] = Field(default_factory=list)
    specificity: int = 0
    fallback_used: bool = False
    probabilities: dict[str, float] = Field(default_factory=dict)
    decided: bool = False
    note: str = ""


class MappingStats(BaseModel):
    """What the mapping cost."""

    model_config = ConfigDict(extra="forbid")

    jev_calls: int = 0
    jev_questions: int = 0
    jev_input_tokens: int = 0
    jev_output_tokens: int = 0
    jev_errors: list[str] = Field(default_factory=list)


# %% Internal beam bookkeeping


@dataclass
class _Path:
    """One candidate path through the class hierarchy."""

    uri: str
    names: list[str] = field(default_factory=list)
    log_score: float = 0.0
    decisions: int = 0

    @property
    def score(self) -> float:
        """Geometric mean of the edge probabilities along the path."""
        if self.decisions == 0:
            return 1.0
        return math.exp(self.log_score / self.decisions)


@dataclass
class _WindowRequest:
    """A choice question whose options are offered in windows.

    `key_map` maps an option label back onto the ontology term it stands
    for; `tiers` carries the specificity tier of each option (properties
    only). `min_confidence` overrides the call-wide floor for this question
    alone — that is how a class question and a property question can travel
    in the same request while keeping their own confidence floors.
    """

    qid: str
    instructions: str
    windows: list[dict[str, str]]
    none_label: str | None = None
    key_map: dict[str, str] = field(default_factory=dict)
    tiers: dict[str, int] = field(default_factory=dict)
    min_confidence: float = 0.0


@dataclass
class ClassRepairRequest:
    """One class the strict gate refused, and what it has to satisfy.

    `types` are the type constraints (class URIs) the new class must
    satisfy for the rejected relation to become legal — the very same rule
    the gate applies, so a repair can never propose a class the gate would
    refuse again.
    """

    entity: str
    side: str
    rejected_class: str
    relation: str
    types: list[str] = field(default_factory=list)
    complaint: str = ""


@dataclass
class JevOutcome:
    """What one windowed question ended up deciding.

    `answer` is set only when Jev *committed* to an option with enough
    confidence. `window` says which window produced it (-1 when the answer
    was a last-resort weak pick). `probabilities` merges every option
    probability Jev produced across all the windows of the question — the
    only record of how it ranked the candidates it would not commit to,
    and what the notebook shows next to a fallback decision.
    """

    answer: JevAnswer | None = None
    window: int = -1
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass
class _PropertyPlan:
    """Everything one (subject, relation, object) mapping needs, per phase.

    The windows are kept as plain option lists rather than as requests: every
    window is an *independent* choice question (it carries its own escape
    hatch), so all of them can travel in the same request instead of costing
    one round trip per round of rejections.
    """

    key: str
    mapping: PropertyMapping
    instructions: str = ""
    near_instructions: str = ""
    strict_uris: list[str] = field(default_factory=list)
    key_map: dict[str, str] = field(default_factory=dict)
    tiers: dict[str, int] = field(default_factory=dict)
    specificity: dict[str, int] = field(default_factory=dict)
    strict_windows: list[dict[str, str]] = field(default_factory=list)
    relaxed_windows: list[dict[str, str]] = field(default_factory=list)


_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _tokens(text: str) -> set[str]:
    """Split a text into comparable tokens.

    CamelCase is split (`isMemberOf` -> `is member of`) so that a DUL
    relation name and a natural-language predicate end up on the same
    footing; that split alone is what makes the term affinity work at all.
    """
    spaced = _CAMEL.sub(" ", text)
    return {t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t}


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    """Split a list into consecutive chunks of at most `size` items."""
    size = max(1, size)
    return [items[i : i + size] for i in range(0, len(items), size)]


def pair_key(subject: str, relation: str, obj: str) -> str:
    """Stable key of one (subject, relation, object) mapping request."""
    return f"{subject}|{relation}|{obj}"
