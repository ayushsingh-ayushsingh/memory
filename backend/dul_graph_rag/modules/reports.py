from __future__ import annotations

import uuid
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from .gate import ProposedTriple, _short


# %% Cell 11 — REPORTS + FACT IDENTITY (pydantic I/O throughout)
#
# Every operation in this notebook answers with one of these models, so the
# printed JSON *is* the API contract. The identity rules live here too:
# a fact is `subject|relation|object`, and both the graph uuid and the vector
# point id are UUID5 of it — which is what makes every write an **upsert**
# and every re-run idempotent, never a duplicate.


def triple_key(t: dict[str, Any] | ProposedTriple) -> str:
    """Stable fact key: subject short-id | relation short-name | object short-id."""
    d = t if isinstance(t, dict) else t.model_dump()
    return (
        f"{d.get('subject_id', '?')}|{_short(str(d.get('relation', '?')))}|"
        f"{d.get('object_id', '?')}"
    )


def triple_key_of(triple: dict[str, Any]) -> str:
    """Alias used by the CRUD cells (same derivation as `triple_key`)."""
    return triple_key(triple)


def node_uuid(group: str, node_id: str) -> str:
    """Deterministic entity-node uuid (group-scoped, stable across re-runs)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"dul-node:{group}:{node_id}"))


def edge_uuid(group: str, fact_key: str) -> str:
    """Deterministic fact-edge uuid (group-scoped, stable across re-runs)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"dul-edge:{group}:{fact_key}"))


class WriteOutcome(BaseModel):
    """What a write actually did (graph + vector mirror)."""

    model_config = ConfigDict(extra="forbid")

    node_uuids: list[str] = Field(default_factory=list)
    edge_uuids: list[str] = Field(default_factory=list)
    vector_status: str = "skipped"
    vector_detail: str = ""
    warnings: list[str] = Field(default_factory=list)


class CreateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    fact_key: str
    episode_uuid: str | None = None
    issues: list[str] = Field(default_factory=list)
    vector_status: str = ""
    warnings: list[str] = Field(default_factory=list)


class BulkReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created: int
    rejected: int
    edge_uuids: list[str] = Field(default_factory=list)
    rejected_details: list[str] = Field(default_factory=list)
    vector_status: str = ""
    warnings: list[str] = Field(default_factory=list)


class BulkDeleteReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: int
    missing: int
    details: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DeleteReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    fact_key: str
    detail: str = ""
    vector_status: str = ""
    warnings: list[str] = Field(default_factory=list)


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="allow")

    fact: str
    score: float
    provenance: str
    created_at: str | None = Field(
        default=None, description="ISO timestamp of the source record"
    )
    ref: str | None = Field(
        default=None, description="fact_key (graph facts) or doc_id (chunks)"
    )


class SearchReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    hits: list[SearchHit] = Field(default_factory=list)
    legs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def fact_payload(
    prop: ProposedTriple,
    key: str,
    group: str,
    episode_uuid: str | None = None,
    *,
    version: int = 0,
    doc_id: str | None = None,
) -> dict[str, Any]:
    """Vector-mirror payload for one fact (graph and mirror stay in sync).

    `created_at` / `deleted_at` / `superseded_at` are what the search weights
    are computed from: data written earlier ages, a delete and an update only
    *flag* data, so the payload has to carry the flag even though nothing is
    ever removed from the collection.
    """
    from datetime import UTC, datetime

    payload: dict[str, Any] = {
        "fact_key": key,
        "fact_sentence": prop.fact_sentence,
        "subject": prop.subject_name,
        "relation": _short(prop.relation),
        "edge_name": prop.relation_name,
        "object": prop.object_name,
        "source": prop.source,
        "subject_class": prop.subject_class,
        "object_class": prop.object_class,
        "group_id": group,
        "version": version,
        "created_at": datetime.now(UTC).isoformat(),
        "deleted": False,
        "superseded": False,
    }
    if episode_uuid:
        payload["episode_uuid"] = episode_uuid
    if doc_id:
        payload["doc_id"] = doc_id
    return payload
