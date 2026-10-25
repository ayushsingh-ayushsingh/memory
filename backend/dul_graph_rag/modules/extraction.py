from __future__ import annotations

import asyncio
import re

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from .clients import groq_api_key
from .gate import ProposedTriple
from .jev import JevUsage
from .mapper_types import ClassMapping, PropertyMapping
from .settings import Settings, get_settings


# %% Cell 18 — TEXT -> DUL TRIPLES (LLM extraction + Jev mapping + gate retry)
#
# The split of labour is strict:
#
# * **Groq** (`openai/gpt-oss-120b`) extracts the *surface* entities and
#   relations of a text chunk. It never sees the ontology and it never names a
#   DUL class or property.
# * **Jev** (TypeSafe) decides which DOLCE class every entity is and which
#   DOLCE object property expresses every relation — with confidence scores.
# * **The gate** disposes of the result: a triple that does not satisfy the DUL
#   vocabulary, the domain/range constraints and the edge map is rejected, and
#   the reason is handed back to Jev together with *different* candidate choices.
#
# Jev accepts at most `jev_max_choices` options per question, so a question with
# more candidates is asked in **windows**; every window of every stage travels in
# one request. The whole mapping therefore costs a handful of round trips, no
# matter how long the text is.

# %% Extraction models (the only place an LLM is used)


class Entities(BaseModel):
    """All entities of a text chunk (surface forms, no ontology)."""

    model_config = ConfigDict(extra="ignore")

    chain_of_thought: str = Field(
        default="", description="Your end-to-end thought process for entity extraction"
    )
    entity_list: list[str] = Field(
        default_factory=list, description="All the entities from the text chunk"
    )


class Relations(BaseModel):
    """All important relations of a text chunk (surface forms, no ontology)."""

    model_config = ConfigDict(extra="ignore")

    chain_of_thought: str = Field(
        default="", description="Your end-to-end thought process for relation extraction"
    )
    relations_list: list[str] = Field(
        default_factory=list,
        description=(
            "All possible relations that could be extracted from the text chunk, "
            "in snake_case, without the entities"
        ),
    )


class ExtractionResult(BaseModel):
    """What the LLM extracted (surface level only)."""

    model_config = ConfigDict(extra="forbid")

    entities: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    entity_notes: str = ""
    relation_notes: str = ""


class PairRelation(BaseModel):
    """An entity pair and the surface relation Jev assigned to it."""

    model_config = ConfigDict(extra="forbid")

    subject: str
    relation: str
    object: str
    direction: str = "forward"
    confidence: float = 0.0
    probabilities: dict[str, float] = Field(default_factory=dict)


class MappedTriple(BaseModel):
    """A triple with the confidences that produced it."""

    model_config = ConfigDict(extra="forbid")

    triple: ProposedTriple
    pair_key: str = ""
    surface_relation: str = ""
    pair_confidence: float = 0.0
    class_confidence: float = 0.0
    property_confidence: float = 0.0
    property_tier: int = 3
    subject_class_name: str = ""
    object_class_name: str = ""
    gate_ok: bool = True
    gate_issues: list[str] = Field(default_factory=list)


class GateRow(BaseModel):
    """One row of the strict-gate report."""

    model_config = ConfigDict(extra="forbid")

    subject: str
    subject_class: str
    relation: str
    relation_name: str
    object: str
    object_class: str
    valid: bool
    detail: str


class UnmappedPair(BaseModel):
    """A surface pair that never became a triple, and why."""

    model_config = ConfigDict(extra="forbid")

    subject: str
    relation: str
    object: str
    reason: str


class MappingResult(BaseModel):
    """The outcome of the mapping stage (no writes yet)."""

    model_config = ConfigDict(extra="forbid")

    extraction: ExtractionResult = Field(default_factory=ExtractionResult)
    pair_relations: list[PairRelation] = Field(default_factory=list)
    class_mappings: dict[str, ClassMapping] = Field(default_factory=dict)
    property_mappings: dict[str, PropertyMapping] = Field(default_factory=dict)
    triples: list[MappedTriple] = Field(default_factory=list)
    gate_rows: list[GateRow] = Field(default_factory=list)
    unmapped: list[UnmappedPair] = Field(default_factory=list)
    retries: int = 0
    usage: JevUsage = Field(default_factory=JevUsage)
    notes: list[str] = Field(default_factory=list)


class IngestReport(BaseModel):
    """Everything that happened during one ingestion run."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    mapping: MappingResult = Field(default_factory=MappingResult)
    created: int = 0
    rejected: int = 0
    rejected_details: list[str] = Field(default_factory=list)
    vector_status: str = ""
    warnings: list[str] = Field(default_factory=list)
    usage: JevUsage = Field(default_factory=JevUsage)


# %% Helpers


def slugify(value: str) -> str:
    """Deterministic node id from a surface name."""
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "entity"


def humanize(relation: str) -> str:
    """`is_employee_of` -> `is employee of` (the human edge context).

    Surface relation names come straight from the extraction model, so the
    parts are stripped: a stray space would otherwise leak into the edge name
    and into the fact sentence the graph is searched on.
    """
    return " ".join(
        part.strip() for part in relation.replace("-", "_").split("_") if part.strip()
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        cleaned = value.strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def relation_option_limit(settings: Settings) -> int:
    """How many surface relations fit into one Choice question.

    The relations are the *options* of one Jev question, so they share the
    option budget with the "none of these" escape hatch.
    """
    s = settings
    slots = s.jev_max_choices - (1 if s.jev_include_none_option else 0)
    return max(1, min(s.max_extracted_relations, slots))


# %% Stage 1 — LLM extraction (the only LLM call in the pipeline)


async def extract_entities_relations(
    text: str, settings: Settings | None = None
) -> ExtractionResult:
    """Extract surface entities and relations with the configured LLM."""

    from pydantic_ai import Agent
    from pydantic_ai.models.groq import GroqModel, GroqModelSettings
    from pydantic_ai.providers.groq import GroqProvider


    s = settings or get_settings()
    model_settings = GroqModelSettings(
        max_tokens=s.groq_max_tokens,
        temperature=s.groq_temperature,
        groq_reasoning_format=s.groq_reasoning_format,  # type: ignore[typeddict-item]
        groq_reasoning_effort=s.groq_reasoning_effort,  # type: ignore[typeddict-item]
    )
    model = GroqModel(
        s.groq_model, provider=GroqProvider(api_key=groq_api_key()), settings=model_settings
    )
    entity_agent = Agent(
        model,
        output_type=Entities,
        system_prompt=(
            "You extract the entities of a text chunk: people, organizations, "
            "places, times, dates, events, teams, products, numbers and the "
            "like. Use the surface form as it appears in the text. Never name "
            "an ontology class and never explain the ontology."
        ),
    )
    relation_agent = Agent(
        model,
        output_type=Relations,
        system_prompt=(
            "You extract the relations of a text chunk. A relation is a short "
            "snake_case predicate WITHOUT the entities, e.g. is_employee_of, "
            "is_manager_of, works_in, is_located_in, is_colleague_of. "
            "Return at most "
            f"{relation_option_limit(s)} of them, most important first. "
            "Never name an ontology class or property."
        ),
    )
    entities_run, relations_run = await asyncio.gather(
        entity_agent.run(text), relation_agent.run(text)
    )
    entities = _dedupe(entities_run.output.entity_list)
    relations = _dedupe(relations_run.output.relations_list)
    return ExtractionResult(
        entities=entities[: s.jev_max_entities],
        relations=relations[: relation_option_limit(s)],
        entity_notes=entities_run.output.chain_of_thought,
        relation_notes=relations_run.output.chain_of_thought,
    )
