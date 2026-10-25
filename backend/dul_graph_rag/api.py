from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .modules.crud import (
    manual_bulk_create,
    manual_bulk_delete,
    manual_bulk_delete_docs,
    manual_create_triple,
    manual_delete_triple,
    manual_search,
    manual_stats,
    manual_update_triple,
)
from .modules.longtext import ExtractReport, extract_long_text
from .modules.reports import (
    BulkDeleteReport,
    BulkReport,
    CreateReport,
    DeleteReport,
    SearchReport,
)
from .modules.settings import get_settings

logger = logging.getLogger(__name__)

async def _auth_guard(request: Request) -> dict[str, Any] | None:
    """Per-request auth guard.

    When ``DUL_REQUIRE_AUTH`` is true, verifies the Better Auth JWT from the
    ``Authorization: Bearer <jwt>`` header using the app's verifier.  When
    false (the default), it is a no-op so the endpoints can be exercised with
    curl.  The setting is read per request from the settings singleton, so it
    can be flipped without a restart.
    """
    if not get_settings().require_auth:
        return None

    from fastapi import HTTPException, status
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

    from src.auth import get_jwks_client

    scheme = HTTPBearer(auto_error=False)
    credentials: HTTPAuthorizationCredentials | None = await scheme(request)
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    import jwt as pyjwt

    try:
        key = get_jwks_client().get_signing_key_from_jwt(token)
        import os

        issuer = os.getenv("BETTER_AUTH_ISSUER", os.getenv("BETTER_AUTH_URL", "")).rstrip("/")
        audience = os.getenv("BETTER_AUTH_AUDIENCE", os.getenv("BETTER_AUTH_URL", "")).rstrip("/")
        return pyjwt.decode(
            token,
            key.key,
            algorithms=["EdDSA"],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except Exception as exc:  # noqa: BLE001 — any failure is a 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# Applied to every /dul route; harmless when auth is off.
router = APIRouter(
    prefix="/dul",
    tags=["dul-graph-rag"],
    dependencies=[Depends(_auth_guard)],
)


# %% Session singleton (opened lazily, closed on shutdown)
#
# The OntologySession owns the Jev client and the Graphiti/FalkorDB driver.
# It is expensive to open (preflight + ontology self-check + connection), so
# it is opened once per process and reused. A lock serialises concurrent
# first-requests so only one open() runs.


class SessionHolder:
    """Process-wide holder for the single OntologySession."""

    def __init__(self) -> None:
        self._session: Any = None
        self._lock = asyncio.Lock()

    async def get(self) -> Any:
        if self._session is not None and getattr(self._session, "_opened", False):
            return self._session
        async with self._lock:
            if self._session is not None and getattr(self._session, "_opened", False):
                return self._session
            from .modules.session import OntologySession

            session = OntologySession()
            await session.open()
            self._session = session
            return session

    async def close(self) -> None:
        async with self._lock:
            if self._session is not None:
                await self._session.close()
                self._session = None


HOLDER = SessionHolder()


async def get_session() -> Any:
    """FastAPI dependency: the shared OntologySession."""
    return await HOLDER.get()


# %% Request / response models


class ExtractRequest(BaseModel):
    """One long text to coref-resolve, chunk, embed and extract."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="The long conversation / document")
    group: str | None = Field(default=None, description="Logical partition override")
    doc_id: str | None = Field(
        default=None, description="Supply to reuse a doc id (re-ingest / upsert)"
    )
    embed_chunks: bool = Field(
        default=True, description="Store the chunks in Qdrant (semantic recall)"
    )


class SearchRequest(BaseModel):
    """Unified search: fulltext + semantic across FalkorDB and Qdrant."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    limit: int | None = Field(default=None, ge=1, le=200)
    group: str | None = None
    include_deleted: bool = Field(default=False)
    include_superseded: bool = Field(default=False)
    include_chunks: bool = Field(default=True)


class TripleRequest(BaseModel):
    """One triple to create / update (DUL-enforced).

    The class and relation fields accept either a full DUL URI or the short
    DUL name (``"Agent"``, ``"hasLocation"``); the URI form is resolved on
    the server.  ``subject_id`` / ``object_id`` are optional and default to a
    slug of the corresponding name, so a human only has to supply the two
    names and the relation.
    """

    model_config = ConfigDict(extra="forbid")

    subject_id: str | None = None
    subject_name: str = Field(min_length=1)
    subject_class: str | None = Field(
        default=None,
        description=(
            "DUL class (short name or full URI) of the subject. Omit it and "
            "the server infers a class from the relation's declared domain."
        ),
    )
    relation: str = Field(
        min_length=1,
        description="DUL object property (short name or full URI)",
    )
    relation_name: str = ""
    object_id: str | None = None
    object_name: str = Field(min_length=1)
    object_class: str | None = Field(
        default=None,
        description=(
            "DUL class (short name or full URI) of the object. Omit it and "
            "the server infers a class from the relation's declared range."
        ),
    )
    fact_sentence: str = ""
    source: str = "api"
    group: str | None = None
    supersedes: list[str] = Field(
        default_factory=list,
        description=(
            "Update only: extra fact_keys to soft-supersede, on top of the "
            "live facts that share this triple's (subject, relation)."
        ),
    )


def _resolve_term(value: str, kind: str, deps: dict[str, Any]) -> str:
    """Resolve a short DUL name (``"Agent"``) or full URI to the canonical URI.

    ``kind`` is ``"class"`` or ``"property"``.  A value that already looks
    like a URI is validated against the ontology's vocabulary; a short name is
    matched case-insensitively against the gate's schema.  Anything unresolvable
    raises a 422 with the reason, so bad terms never reach the gate silently.
    """
    from .modules.ontology import local_name

    value = value.strip()
    schema = deps["schema"]
    vocabulary = (
        set(schema["classes"]) if kind == "class" else set(schema["object_properties"])
    )
    if value in vocabulary:
        return value
    # A URI that is not in the gate vocabulary is a hard error (fail-closed).
    if "#" in value or value.rstrip("/").rsplit("/", 1)[-1] not in ("", value):
        raise HTTPException(
            status_code=422,
            detail=f"unknown DUL {kind}: {value} (not in the gate vocabulary)",
        )
    # Short-name lookup: case-insensitive match on the local name.
    target = value.lower()
    for uri in vocabulary:
        if local_name(uri).lower() == target:
            return uri
    raise HTTPException(
        status_code=422,
        detail=f"unknown DUL {kind} name: {value!r}",
    )


def _infer_class(declared: list[str], deps: dict[str, Any]) -> str:
    """Pick a class for an endpoint caller who did not name one.

    ``declared`` is the relation's effective domain (subject) or range
    (object) from the ontology lineage.  The gate demands that the class be a
    subclass of *every* declared constraint, so:

    1. With one constraint (the common case) the declared class itself fits.
    2. With several, any declared class that fits all of them wins (the most
       specific one, so the triple stays informative).
    3. Otherwise the shallowest common descendant of the constraints is the
       least committal valid choice.
    4. If the relation declares no constraint, fall back to the ontology
       root; the gate then rejects the relation itself with its own clear
       message (a relation without domain/range is never writable anyway).
    """
    from .modules.ontology import get_ontology
    from .modules.schema import is_subclass_of

    if not declared:
        return get_ontology().root_class
    ancestors = deps["ancestors"]
    classes = list(deps["schema"]["classes"])

    def fits(candidate: str) -> bool:
        return all(is_subclass_of(candidate, d, ancestors) for d in declared)

    declared_ok = [d for d in declared if d in classes and fits(d)]
    if declared_ok:
        # Most specific declared constraint that satisfies all of them.
        return max(declared_ok, key=lambda c: len(ancestors.get(c, {c})))
    descendants = [c for c in classes if fits(c)]
    if descendants:
        # Shallowest common descendant: valid, but as general as possible.
        return min(descendants, key=lambda c: len(ancestors.get(c, {c})))
    # Constraints are unsatisfiable: use the first so the gate reports the
    # real problem (domain/range mismatch) instead of an unknown class.
    return declared[0]


def _resolve_triple(body: TripleRequest, deps: dict[str, Any]) -> dict[str, Any]:
    """Turn a human-friendly ``TripleRequest`` into a gate-ready triple dict."""
    from .modules.extraction import slugify
    from .modules.ontology import local_name

    relation = _resolve_term(body.relation, "property", deps)
    lineage = deps["lineage"].get(relation, {"domain": [], "range": []})
    if body.subject_class is None:
        subject_class = _infer_class(list(lineage.get("domain", [])), deps)
    else:
        subject_class = _resolve_term(body.subject_class, "class", deps)
    if body.object_class is None:
        object_class = _infer_class(list(lineage.get("range", [])), deps)
    else:
        object_class = _resolve_term(body.object_class, "class", deps)
    subject_name = body.subject_name.strip()
    object_name = body.object_name.strip()
    relation_label = body.relation_name.strip() or local_name(relation)
    # `fact_sentence` is required by the gate schema; build a readable one
    # when the caller does not supply it.
    fact_sentence = body.fact_sentence.strip() or (
        f"{subject_name} {relation_label} {object_name}."
    )
    return {
        "subject_id": body.subject_id or slugify(subject_name),
        "subject_name": subject_name,
        "subject_class": subject_class,
        "relation": relation,
        "relation_name": relation_label,
        "object_id": body.object_id or slugify(object_name),
        "object_name": object_name,
        "object_class": object_class,
        "fact_sentence": fact_sentence,
        "source": body.source,
    }


class BulkTripleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    triples: list[TripleRequest] = Field(min_length=1)
    group: str | None = None


class BulkDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_keys: list[str] = Field(default_factory=list)
    doc_ids: list[str] = Field(default_factory=list)
    group: str | None = None


class DeleteDocRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    group: str | None = None


# %% Endpoints


@router.get("/health")
async def health(session: Annotated[Any, Depends(get_session)]) -> dict[str, Any]:
    """Liveness + dependency snapshot for the DUL pipeline."""
    settings = get_settings()
    from .modules.preflight import preflight

    report = await asyncio.to_thread(preflight, settings)
    return {
        "status": "ok",
        "group": session.group,
        "services": {c.name: c.ok for c in report.services},
        "settings": {
            "chunk_size": settings.chunk_size,
            "coref_enabled": settings.coref_enabled,
            "extract_concurrency": settings.extract_concurrency,
            "recency_half_life_days": settings.recency_half_life_days,
        },
    }


@router.post("/extract", response_model=ExtractReport)
async def extract(
    body: ExtractRequest,
    session: Annotated[Any, Depends(get_session)],
) -> ExtractReport:
    """Coreference-resolve, chunk (no overlap), embed, extract and write.

    This is the main ingestion endpoint. The LLM is used only for
    entity/relation extraction (once per chunk, run concurrently). Jev does
    all ontology mapping. Only gate-passing triples reach FalkorDB.
    """
    try:
        return await extract_long_text(
            body.text,
            session=session,
            group=body.group,
            doc_id=body.doc_id,
            embed_chunks=body.embed_chunks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/search", response_model=SearchReport)
async def search(
    body: SearchRequest,
    session: Annotated[Any, Depends(get_session)],
) -> SearchReport:
    """Fulltext + semantic search across FalkorDB and Qdrant, reranked."""
    return await manual_search(
        session.graphiti,
        session.deps,
        body.query,
        limit=body.limit,
        group=body.group or session.group,
        include_deleted=body.include_deleted,
        include_superseded=body.include_superseded,
        include_chunks=body.include_chunks,
    )


@router.post("/facts", response_model=CreateReport)
async def create_fact(
    body: TripleRequest,
    session: Annotated[Any, Depends(get_session)],
) -> CreateReport:
    """Create one DUL-enforced triple (no LLM, no Jev — pure gate + write)."""
    payload = _resolve_triple(body, session.deps)
    return await manual_create_triple(
        session.graphiti, session.deps, payload, group=body.group or session.group
    )


@router.post("/facts/bulk", response_model=BulkReport)
async def bulk_create_facts(
    body: BulkTripleRequest,
    session: Annotated[Any, Depends(get_session)],
) -> BulkReport:
    """Create many DUL-enforced triples in one call."""
    triples = [_resolve_triple(t, session.deps) for t in body.triples]
    return await manual_bulk_create(
        session.graphiti, session.deps, triples, group=body.group or session.group
    )


@router.put("/facts", response_model=CreateReport)
async def update_fact(
    body: TripleRequest,
    session: Annotated[Any, Depends(get_session)],
) -> CreateReport:
    """Update = soft-supersede the old value(s), write a new version.

    Supersedes the live facts for this triple's (subject, relation) plus any
    explicit ``supersedes`` fact_keys.  Nothing is deleted.
    """
    payload = _resolve_triple(body, session.deps)
    return await manual_update_triple(
        session.graphiti,
        session.deps,
        payload,
        group=body.group or session.group,
        supersedes=list(body.supersedes),
    )


async def _bulk_delete(
    body: BulkDeleteRequest, session: Any
) -> BulkDeleteReport:
    """Shared handler for bulk soft-delete (by fact_keys and/or doc_ids)."""
    group = body.group or session.group
    report = BulkDeleteReport(deleted=0, missing=0, details=[], warnings=[])

    if body.doc_ids:
        doc = await manual_bulk_delete_docs(session.graphiti, body.doc_ids, group=group)
        # doc deletion reports flagged edge counts, not per-key outcomes.
        report.details.append(
            f"docs:{','.join(body.doc_ids)} -> {doc.get('edges_flagged', 0)} edge(s) flagged"
        )
        report.warnings.extend(doc.get("warnings", []))

    if body.fact_keys:
        key_report = await manual_bulk_delete(session.graphiti, body.fact_keys, group=group)
        report.deleted += key_report.deleted
        report.missing += key_report.missing
        report.details.extend(key_report.details)
        report.warnings.extend(key_report.warnings)

    return report


# NOTE: the bulk DELETE route is registered *before* ``/facts/{fact_key}`` so a
# request to ``/facts/bulk`` is never swallowed by the parameterized route.
@router.delete("/facts", response_model=BulkDeleteReport)
async def bulk_delete_facts(
    body: BulkDeleteRequest,
    session: Annotated[Any, Depends(get_session)],
) -> BulkDeleteReport:
    """Soft-delete many facts by fact_key and/or whole documents by doc_id."""
    return await _bulk_delete(body, session)


@router.post("/facts/bulk-delete", response_model=BulkDeleteReport)
async def bulk_delete_facts_post(
    body: BulkDeleteRequest,
    session: Annotated[Any, Depends(get_session)],
) -> BulkDeleteReport:
    """POST alias for bulk soft-delete (for clients that cannot send a body on DELETE)."""
    return await _bulk_delete(body, session)


@router.delete("/facts/{fact_key}", response_model=DeleteReport)
async def delete_fact(
    fact_key: str,
    session: Annotated[Any, Depends(get_session)],
    group: str | None = None,
) -> DeleteReport:
    """Soft-delete one fact by fact_key (flagged, not removed)."""
    return await manual_delete_triple(
        session.graphiti, fact_key, group=group or session.group
    )


@router.delete("/docs")
async def delete_doc(
    body: DeleteDocRequest,
    session: Annotated[Any, Depends(get_session)],
) -> dict[str, Any]:
    """Soft-delete every fact and chunk that came from one document."""
    return await manual_bulk_delete_docs(
        session.graphiti, [body.doc_id], group=body.group or session.group
    )


@router.get("/stats")
async def stats(
    session: Annotated[Any, Depends(get_session)],
    group: str | None = None,
) -> dict[str, Any]:
    """Entity/edge counts + flag counts + sample + Qdrant counts."""
    return await manual_stats(session.graphiti, group=group or session.group)


__all__ = ["router", "HOLDER"]
