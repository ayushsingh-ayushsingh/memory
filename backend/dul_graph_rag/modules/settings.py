from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from pydantic import (
    AliasChoices,
    Field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import ENV_FILE


# %% Cell 02 — SETTINGS: every endpoint, store name, model id and flag from env
#
# Nothing in this file hardcodes a host, port, graph name, model id or
# collection name. They are resolved **once** here (process env + .env) and
# every cell below reads them through ``get_settings()``.
#
# Alias policy: every field accepts its current env name plus the legacy one,
# so existing .env files keep working.

# NOTE: `PROJECT_ROOT` / `ENV_FILE` used to be derived from
# `Path(__file__).parent` -- `backend/notebooks/`, one level below the
# real project root -- so `.env`, `graph.json` and `data/*.json` were
# never found and every setting fell back to its default. They are now
# resolved by `paths.py`, which walks up to the directory holding
# `pyproject.toml` (the `backend/` directory).


class Settings(BaseSettings):
    """Resolved runtime configuration for this notebook."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # %% FalkorDB (Redis protocol)
    falkordb_host: str = Field(
        "127.0.0.1", validation_alias=AliasChoices("FALKORDB_HOST")
    )
    falkordb_port: int = Field(
        6379, validation_alias=AliasChoices("FALKORDB_PORT")
    )
    falkordb_user: str = Field(
        "default", validation_alias=AliasChoices("FALKORDB_USER")
    )
    falkordb_password: str = Field(
        "password", validation_alias=AliasChoices("FALKORDB_PASSWORD")
    )
    falkordb_timeout_s: float = Field(
        10.0, validation_alias=AliasChoices("FALKORDB_TIMEOUT_S")
    )

    # %% Graph stores (two schemas, by design — see the STORES cell)
    graphiti_graph: str = Field(
        "dul_graphiti",
        validation_alias=AliasChoices("FALKORDB_GRAPH_GRAPHITI", "DUL_GRAPHITI_GRAPH"),
    )
    legacy_graph: str = Field(
        "dul_memory_test",
        validation_alias=AliasChoices("FALKORDB_GRAPH_LEGACY", "FALKORDB_GRAPH"),
    )

    # %% Logical partitions inside the Graphiti store
    graphiti_group: str | None = Field(
        None, validation_alias=AliasChoices("DUL_GRAPHITI_GROUP")
    )
    manual_group: str = Field(
        "dul_manual", validation_alias=AliasChoices("DUL_MANUAL_GROUP")
    )

    # %% Qdrant (vector mirror of the fact edges)
    qdrant_url: str = Field(
        "http://localhost:6333", validation_alias=AliasChoices("QDRANT_URL")
    )
    qdrant_api_key: str | None = Field(
        None, validation_alias=AliasChoices("QDRANT_API_KEY")
    )
    qdrant_timeout_s: float = Field(
        5.0, validation_alias=AliasChoices("QDRANT_TIMEOUT_S")
    )
    fact_collection: str = Field(
        "dul_facts", validation_alias=AliasChoices("DUL_FACT_COLLECTION")
    )
    # Mirror is best-effort by default (graph write must not die with Qdrant).
    vector_mirror_enabled: bool = Field(
        True, validation_alias=AliasChoices("DUL_VECTOR_MIRROR_ENABLED")
    )
    # Fail-closed switch: reject writes when the mirror is unreachable.
    vector_mirror_required: bool = Field(
        False, validation_alias=AliasChoices("DUL_VECTOR_MIRROR_REQUIRED")
    )

    # %% Models
    dense_model: str = Field(
        "sentence-transformers/all-MiniLM-L6-v2",
        validation_alias=AliasChoices("DUL_DENSE_MODEL"),
    )
    rerank_model: str = Field(
        "jinaai/jina-reranker-v2-base-multilingual",
        validation_alias=AliasChoices("DUL_RERANK_MODEL"),
    )
    groq_model: str = Field(
        "openai/gpt-oss-120b", validation_alias=AliasChoices("DUL_GROQ_MODEL")
    )
    groq_api_key: str | None = Field(
        None, validation_alias=AliasChoices("GROQ_API_KEY")
    )
    groq_temperature: float = Field(
        0.0, validation_alias=AliasChoices("DUL_GROQ_TEMPERATURE")
    )
    groq_max_tokens: int = Field(
        2000, validation_alias=AliasChoices("DUL_GROQ_MAX_TOKENS")
    )
    # Reasoning models (gpt-oss) spend reasoning tokens from the same budget.
    groq_reasoning_effort: str = Field(
        "low", validation_alias=AliasChoices("DUL_GROQ_REASONING_EFFORT")
    )
    groq_reasoning_format: str = Field(
        "parsed", validation_alias=AliasChoices("DUL_GROQ_REASONING_FORMAT")
    )

    # %% Limits & tunables (no magic numbers anywhere else in the file)
    max_search_limit: int = Field(
        20, validation_alias=AliasChoices("DUL_LIMIT_MAX_SEARCH_RESULTS")
    )
    max_triples_per_chunk: int = Field(
        25, validation_alias=AliasChoices("DUL_LIMIT_MAX_TRIPLES_PER_CHUNK")
    )
    # How many surface relations the extractor may propose. The relations
    # become the *options* of one Jev Choice question, so the ceiling is
    # also bounded by the Choice limit (the "none of these" escape hatch
    # takes one slot) — the pipeline takes the smaller of the two.
    max_extracted_relations: int = Field(
        9, validation_alias=AliasChoices("DUL_LIMIT_MAX_EXTRACTED_RELATIONS")
    )
    max_answer_chars: int = Field(
        2000, validation_alias=AliasChoices("DUL_LIMIT_MAX_ANSWER_CHARS")
    )
    episode_name_max_len: int = Field(
        200, validation_alias=AliasChoices("DUL_LIMIT_EPISODE_NAME_MAX_LEN")
    )
    error_detail_max_len: int = Field(
        300, validation_alias=AliasChoices("DUL_LIMIT_ERROR_DETAIL_MAX_LEN")
    )
    rate_max_attempts: int = Field(
        4, validation_alias=AliasChoices("DUL_LIMIT_RATE_MAX_ATTEMPTS")
    )
    rate_backoff_base_s: float = Field(
        20.0, validation_alias=AliasChoices("DUL_LIMIT_RATE_BACKOFF_BASE_S")
    )
    rate_backoff_max_s: float = Field(
        90.0, validation_alias=AliasChoices("DUL_LIMIT_RATE_BACKOFF_MAX_S")
    )
    graph_fetch_multiplier: int = Field(
        2, validation_alias=AliasChoices("DUL_LIMIT_GRAPH_FETCH_MULTIPLIER")
    )
    graph_batch_size: int = Field(
        100, validation_alias=AliasChoices("DUL_LIMIT_GRAPH_BATCH_SIZE")
    )
    vector_default_limit: int = Field(
        10, validation_alias=AliasChoices("DUL_LIMIT_VECTOR_DEFAULT_LIMIT")
    )
    scroll_page_size: int = Field(
        256, validation_alias=AliasChoices("DUL_LIMIT_SCROLL_PAGE_SIZE")
    )
    falkor_constraint_timeout_s: float = Field(
        12.0, validation_alias=AliasChoices("DUL_LIMIT_FALKOR_CONSTRAINT_TIMEOUT_S")
    )
    falkor_poll_interval_s: float = Field(
        0.25, validation_alias=AliasChoices("DUL_LIMIT_FALKOR_POLL_INTERVAL_S")
    )
    # Graphiti renders `edge_type_map` into its extraction prompt: a map with
    # thousands of class pairs makes the server reject the request (HTTP 400).
    # Guard the size explicitly.
    max_edge_map_pairs: int = Field(
        500, validation_alias=AliasChoices("DUL_LIMIT_MAX_EDGE_MAP_PAIRS")
    )
    # Field limits of the triple I/O model (the writer's output contract).
    triple_id_max_len: int = Field(
        300, validation_alias=AliasChoices("DUL_LIMIT_TRIPLE_ID_MAX_LEN")
    )
    triple_name_max_len: int = Field(
        1000, validation_alias=AliasChoices("DUL_LIMIT_TRIPLE_NAME_MAX_LEN")
    )
    triple_relation_max_len: int = Field(
        200, validation_alias=AliasChoices("DUL_LIMIT_TRIPLE_RELATION_MAX_LEN")
    )
    triple_fact_max_len: int = Field(
        2000, validation_alias=AliasChoices("DUL_LIMIT_TRIPLE_FACT_MAX_LEN")
    )
    triple_source_max_len: int = Field(
        300, validation_alias=AliasChoices("DUL_LIMIT_TRIPLE_SOURCE_MAX_LEN")
    )

    # %% Ontology namespaces
    dul_namespace: str = Field(
        "http://www.ontologydesignpatterns.org/ont/dul/DUL.owl#",
        validation_alias=AliasChoices("DUL_NS"),
    )

    # %% Ontology export (the parsed source of truth for the mapper)
    ontology_graph_path: str = Field(
        "graph.json", validation_alias=AliasChoices("DUL_ONTOLOGY_GRAPH_PATH")
    )
    ontology_root_class: str = Field(
        "Entity", validation_alias=AliasChoices("DUL_ONTOLOGY_ROOT_CLASS")
    )
    ontology_characteristics_path: str = Field(
        "dul_property_characteristics.json",
        validation_alias=AliasChoices("DUL_ONTOLOGY_CHARACTERISTICS_PATH"),
    )

    # %% TypeSafe / Jev (classification only — the LLM never maps the ontology)
    typesafe_api_key: str | None = Field(
        None, validation_alias=AliasChoices("TYPESAFE_API_KEY")
    )
    jev_model: str = Field("jev-latest", validation_alias=AliasChoices("JEV_MODEL"))
    # Hard protocol limit of the Choice primitive as used by this project.
    jev_max_choices: int = Field(10, validation_alias=AliasChoices("JEV_MAX_CHOICES"))
    jev_timeout_s: float = Field(60.0, validation_alias=AliasChoices("JEV_TIMEOUT_S"))
    jev_api_retries: int = Field(3, validation_alias=AliasChoices("JEV_API_RETRIES"))
    jev_max_concurrency: int = Field(
        8, validation_alias=AliasChoices("JEV_MAX_CONCURRENCY")
    )
    # Guard against one request carrying an unreasonable number of questions.
    # The service answers every question of a request in parallel, so a big
    # budget is what keeps the number of round trips (and therefore the cost)
    # at a minimum.
    jev_max_questions_per_call: int = Field(
        500, validation_alias=AliasChoices("JEV_MAX_QUESTIONS_PER_CALL")
    )
    # Below this confidence a mapping is treated as "not decided yet" and the
    # next candidate window is offered to Jev.
    jev_min_confidence: float = Field(
        0.5, validation_alias=AliasChoices("JEV_MIN_CONFIDENCE")
    )
    # Stage-specific confidence floors (all fall back to `jev_min_confidence`
    # semantics when unset).
    jev_min_class_confidence: float = Field(
        0.5, validation_alias=AliasChoices("JEV_MIN_CLASS_CONFIDENCE")
    )
    jev_min_property_confidence: float = Field(
        0.5, validation_alias=AliasChoices("JEV_MIN_PROPERTY_CONFIDENCE")
    )
    jev_min_pair_confidence: float = Field(
        0.6, validation_alias=AliasChoices("JEV_MIN_PAIR_CONFIDENCE")
    )
    # Ontology-level retries (different candidate window each time).
    jev_mapping_retries: int = Field(
        3, validation_alias=AliasChoices("JEV_MAPPING_RETRIES")
    )
    jev_max_entities: int = Field(24, validation_alias=AliasChoices("JEV_MAX_ENTITIES"))
    # Safety ceiling on the entity pairs probed for relations. The natural
    # bound is the quadratic of `jev_max_entities`; this value must be at
    # least that large for the probe to stay complete.
    jev_max_pairs: int = Field(300, validation_alias=AliasChoices("JEV_MAX_PAIRS"))
    jev_class_beam_width: int = Field(
        4, validation_alias=AliasChoices("JEV_CLASS_BEAM_WIDTH")
    )
    jev_max_class_depth: int = Field(
        6, validation_alias=AliasChoices("JEV_MAX_CLASS_DEPTH")
    )
    jev_probe_both_directions: bool = Field(
        True, validation_alias=AliasChoices("JEV_PROBE_BOTH_DIRECTIONS")
    )
    jev_include_none_option: bool = Field(
        True, validation_alias=AliasChoices("JEV_INCLUDE_NONE_OPTION")
    )
    # Offer near-miss relations (one side of the type constraint fits) as a
    # last resort. They are *not* gate-valid: the strict gate rejects them
    # and says why, and the retry loop then asks Jev again with different
    # choices. Off = the mapper only ever sees strictly valid candidates.
    jev_allow_relaxed_candidates: bool = Field(
        True, validation_alias=AliasChoices("JEV_ALLOW_RELAXED_CANDIDATES")
    )
    # When Jev commits to no DUL relation at all for a relation, fall back to
    # the root of the property hierarchy — DUL's own documented catch-all —
    # instead of dropping the fact. Off = such relations are reported as
    # unmapped and never reach the graph.
    jev_catchall_fallback: bool = Field(
        True, validation_alias=AliasChoices("JEV_CATCHALL_FALLBACK")
    )
    jev_option_comment_chars: int = Field(
        240, validation_alias=AliasChoices("JEV_OPTION_COMMENT_CHARS")
    )
    # Label of the "none of these" escape hatch inside a windowed question.
    jev_none_option_key: str = Field(
        "NONE_OF_THESE", validation_alias=AliasChoices("JEV_NONE_OPTION_KEY")
    )
    # Share of the property corpus above which a token counts as a function
    # word and is ignored when ranking candidate relations.
    jev_affinity_stopword_ratio: float = Field(
        0.05, validation_alias=AliasChoices("JEV_AFFINITY_STOPWORD_RATIO")
    )
    # Tokens are collapsed onto their first N characters before they are
    # compared, so that 'managed' reaches 'manage' and 'members' reaches
    # 'member'.
    jev_affinity_prefix_chars: int = Field(
        5, validation_alias=AliasChoices("JEV_AFFINITY_PREFIX_CHARS")
    )
    # Shorter tokens are ignored entirely. Splitting camelCase turns
    # 'UnitOfMeasure' into {unit, of, measure}, so a grammatical particle
    # such as 'of' can otherwise end up looking like the vocabulary of a
    # class — and every relation named 'is…Of' would then match every
    # predicate that happens to contain the word 'of'.
    jev_affinity_min_token_chars: int = Field(
        3, validation_alias=AliasChoices("JEV_AFFINITY_MIN_TOKEN_CHARS")
    )
    # How many windows of candidates a single relation may be offered in.
    # Every window is one question in a batched request, so this bounds the
    # number of round trips of the property stage.
    jev_max_property_windows: int = Field(
        3, validation_alias=AliasChoices("JEV_MAX_PROPERTY_WINDOWS")
    )
    # How many class candidates a gate repair may put on the table. The
    # candidates are the classes that satisfy the *rejected* relation's type
    # constraint, ranked by closeness to the class the gate refused
    # (siblings, then subclasses, then superclasses).
    jev_max_class_repair_candidates: int = Field(
        24, validation_alias=AliasChoices("JEV_MAX_CLASS_REPAIR_CANDIDATES")
    )
    # How many windows those class candidates may be spread over (every
    # window is one question inside the same batched request).
    jev_max_class_repair_windows: int = Field(
        3, validation_alias=AliasChoices("JEV_MAX_CLASS_REPAIR_WINDOWS")
    )
    # Label stored as the provenance of every triple produced by the pipeline.
    jev_source_label: str = Field(
        "jev-text-chunk", validation_alias=AliasChoices("JEV_SOURCE_LABEL")
    )
    # Logical partition used by the Jev pipeline (inside the Graphiti store).
    jev_group: str = Field("dul_jev", validation_alias=AliasChoices("DUL_JEV_GROUP"))
    # Demo chunk the notebook ships with. It is *input*, never a hardcoded
    # triple: whatever it says still has to be extracted, mapped and gated.
    jev_demo_text: str = Field(
        """
        Ayush Singh
        • +91 93011-27004 • Github • ayushpno@gmail.com • Portfolio • LinkedIn
        Summary
        Software Developer with over three years of hands-on experience in Web Development and Generative AI. I have
        led hackathon teams during college and represented myself at the Amalthea ’25 Hackathon at IIT Gandhinagar. I
        am looking forward to applying my skills by working on meaningful, real-world projects.
        Skills
        Languages & Tools - C, C++, JavaScript, TypeScript, Python, SQL, Linux, Docker, Git and Github.
        Generative AI - Langchain, Langgraph, DSPy, RAG, Graph-RAG, ADK, MCP and A2A protocols.
        Web Technologies - NextJS, Express, MongoDB, React, Node, ShadCN, Drizzle, Astro, HTML and CSS.
        Education
        Lakshmi Narain College of Technology 2026 | Bhopal, MP
        B.Tech in CSE with specialization in AIML - CGPA - 8.52
        12th - Dev Public School - CBSE - 88.8% 2022 |Jashpur, CG
        10th - Kendriya Vidyalaya - CBSE -92.8% 2020 | Jashpur, CG
        Experience
        Maventic Innovative Solutions, AI Trainee Jan 26 - Present | Bhopal
        • Enterprise-ready Agentic platform integrating SAP OData, Google ADK, MCP tooling and A2A Protocol
        CogniAIz, Freelance Developer July - August 2025 | Remote
        • Worked as a Next.js developer, improving accessibility, language internationalization, and animations.
        We Win Limited, Intern - MERN Stack April -July 2025 | Bhopal
        • Worked on dashboards, charts, and UI/UX and backend APIs for the ERP web application using ReactJS.
        Projects
        Graph Agent Platform Agents
        • A platform with multiple agents and tools all connected to each other for solving complex agentic problems.
        • Structured outputs, reasoning, memory, and tools with Google ADK, DSPy, Langchain, Neo4j, MCP and A2A
        AI Persona Agent Persona
        • Personal agent built using Anam AI, where you can interact with a real-time video of an agent, built using
        Web-Sockets, Vite and ReactJS.
        Content Management System Editor
        • Application built using NextJS and PostgreSQL with BetterAuth and AI Integration to help users craft articles, notes
        and content with Rich Text Editing.
        Certifications
        • Cisco Networking: Completed a Virtual Internship in Networking, from May 2024 to July 2024.
        • ServiceNow Cohort: Business Workflows in ServiceNow Platform from November 2024 to December 2024.
        """,
        validation_alias=AliasChoices("JEV_DEMO_TEXT"),
    )
    jev_demo_query: str = Field(
        "Who works at Maventic?",
        validation_alias=AliasChoices("JEV_DEMO_QUERY"),
    )
    example_namespace: str = Field(
        "http://example.org/memory#", validation_alias=AliasChoices("EX_NS")
    )

    # %% Notebook behaviour
    max_retries: int = Field(3, validation_alias=AliasChoices("DUL_MAX_RETRIES"))
    default_search_limit: int = Field(
        5, validation_alias=AliasChoices("DUL_SEARCH_LIMIT")
    )

    # %% Long-context chunking (coreference resolution -> disjoint chunks)
    # Size of one chunk **in characters**, measured on the *resolved* text.
    # ~900 chars is about 230 tokens: short enough for the local dense model
    # (256-token window) and long enough for the extractor to see a whole turn.
    chunk_size: int = Field(
        900, validation_alias=AliasChoices("DUL_CHUNK_SIZE"), ge=100
    )
    # Chunks of the extract path never overlap: the endpoint contract is
    # "one piece of text lives in exactly one chunk", so there is no knob for
    # an overlap here — `chunking.split_no_overlap()` is disjoint by design.
    # Largest piece of raw text handed to the coreference model at once.
    # Longer inputs are cut at paragraph boundaries first (offsets are mapped
    # back, so the clusters still address the original text).
    coref_max_chars: int = Field(
        40_000, validation_alias=AliasChoices("DUL_COREF_MAX_CHARS"), ge=4_000
    )
    coref_device: str = Field(
        "cpu", validation_alias=AliasChoices("DUL_COREF_DEVICE")
    )
    # Set false to chunk without coreference resolution (much cheaper; pronouns
    # stay unresolved, so `it`/`that` no longer carry their referent).
    coref_enabled: bool = Field(
        True, validation_alias=AliasChoices("DUL_COREF_ENABLED")
    )
    # How many chunks may run the (LLM extraction + Jev mapping) pipeline at once.
    extract_concurrency: int = Field(
        4, validation_alias=AliasChoices("DUL_EXTRACT_CONCURRENCY"), ge=1, le=32
    )

    # %% Time-based flagging (updates/deletes never remove data)
    # Age at which an active fact/chunk keeps exactly half of its search weight.
    recency_half_life_days: float = Field(
        14.0, validation_alias=AliasChoices("DUL_RECENCY_HALF_LIFE_DAYS"), gt=0
    )
    # Weight floor of very old data: past facts get less weight, never none.
    recency_floor: float = Field(
        0.2, validation_alias=AliasChoices("DUL_RECENCY_FLOOR"), ge=0.0, le=1.0
    )
    # Multiplier applied to data an update has superseded.
    superseded_weight: float = Field(
        0.35, validation_alias=AliasChoices("DUL_SUPERSEDED_WEIGHT"), ge=0.0, le=1.0
    )
    # Multiplier applied to data a delete has flagged (0 = hidden by default).
    deleted_weight: float = Field(
        0.0, validation_alias=AliasChoices("DUL_DELETED_WEIGHT"), ge=0.0, le=1.0
    )

    # %% Qdrant (chunk vectors written by the extract endpoint)
    chunk_collection: str = Field(
        "dul_chunks", validation_alias=AliasChoices("DUL_CHUNK_COLLECTION")
    )

    # %% HTTP API
    # Auth on the DUL routes. Off by default so the endpoints can be exercised
    # with curl while the frontend is not issuing tokens; turn on in shared
    # deployments (the routes then require the same Better Auth JWT as the
    # notebook-export routes).
    require_auth: bool = Field(
        False, validation_alias=AliasChoices("DUL_REQUIRE_AUTH")
    )

    # %% Data files
    data_dir: str = Field("data", validation_alias=AliasChoices("DUL_DATA_DIR"))

    @model_validator(mode="after")
    def _fill_group(self) -> Settings:
        if not self.graphiti_group:
            object.__setattr__(self, "graphiti_group", self.graphiti_graph)
        if not self.groq_api_key:
            # `.env` is the canonical home for secrets; fall back to process env.
            object.__setattr__(self, "groq_api_key", os.getenv("GROQ_API_KEY") or None)
        if not self.typesafe_api_key:
            object.__setattr__(
                self, "typesafe_api_key", os.getenv("TYPESAFE_API_KEY") or None
            )
        return self

    # %% Introspection
    def describe(self) -> list[dict[str, Any]]:
        """Resolved config rows (key/value) for the notebook display."""
        return [
            {"setting": name, "value": str(getattr(self, name))}
            for name in type(self).model_fields
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (env read once)."""
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings (.env edits in a live session)."""
    get_settings.cache_clear()


#: Process-wide settings singleton. The notebook (and these modules) read
#: configuration through `S` at *class-definition* time -- e.g. inside
#: `StringConstraints(max_length=...)` -- so it has to exist as soon as this
#: module is imported. Mutating it is not supported: call
#: `reset_settings_cache()` and re-read.
S = get_settings()
