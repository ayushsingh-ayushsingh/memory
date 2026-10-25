from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .embeddings import embed_dim, embed_texts
from .settings import Settings, get_settings


# %% Chunk vector store (Qdrant) — the raw text side of the pipeline
#
# The extract endpoint stores two things per input:
#   1. the resolved *chunks* (this store) — for full-text/semantic recall of the
#      source text, with the exact [start, end) offsets in the resolved text.
#   2. the derived *facts* (vectors.fact_collection) — for graph-backed recall.
#
# Chunk writes carry soft flags (`deleted`, `superseded`) and a `doc_id` so a
# document can be re-ingested or deleted without touching the fact graph.
# Nothing is ever physically removed except by an explicit reset.


class ChunkRecord(BaseModel):
    """One disjoint chunk of resolved text."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    doc_id: str
    text: str
    start: int = Field(ge=0, description="char offset in the resolved text")
    end: int = Field(ge=0, description="exclusive char offset in the resolved text")
    index: int = Field(ge=0, description="0-based order of the chunk in the doc")


class ChunkOpResult(BaseModel):
    """Outcome of one chunk-store operation."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    status: str
    detail: str = ""
    count: int = 0
    data: dict[str, Any] = Field(default_factory=dict)


def chunk_point_id(doc_id: str, index: int) -> str:
    """Deterministic point id for a chunk: stable across re-runs."""
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"dul-chunk:{doc_id}:{index}"))


class ChunkStore:
    """Failure-tolerant wrapper around the Qdrant chunk collection."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any = None

    @property
    def collection(self) -> str:
        return self._settings.chunk_collection

    @property
    def enabled(self) -> bool:
        return self._settings.vector_mirror_enabled

    def _client_or_raise(self) -> Any:
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(
                url=self._settings.qdrant_url,
                api_key=self._settings.qdrant_api_key,
                timeout=self._settings.qdrant_timeout_s,
            )
        return self._client

    # --- health
    def status(self) -> ChunkOpResult:
        """Cheap availability probe + point count (never raises)."""
        if not self.enabled:
            return ChunkOpResult(ok=True, status="disabled", detail="mirror disabled")
        try:
            client = self._client_or_raise()
            names = [c.name for c in client.get_collections().collections]
            if self.collection not in names:
                return ChunkOpResult(
                    ok=True, status="missing", detail=self.collection, count=0
                )
            n = client.count(self.collection, exact=True).count
            return ChunkOpResult(
                ok=True, status="up", detail=f"{self.collection}: {n} points", count=n
            )
        except Exception as exc:  # noqa: BLE001 — reported, never raised
            return ChunkOpResult(
                ok=False,
                status="unreachable",
                detail=f"{type(exc).__name__}: {exc}",
                count=-1,
            )

    # --- collection
    def ensure_collection(self, dim: int | None = None) -> ChunkOpResult:
        if not self.enabled:
            return ChunkOpResult(ok=True, status="disabled")
        try:
            client = self._client_or_raise()
            if client.collection_exists(self.collection):
                return ChunkOpResult(ok=True, status="exists", detail=self.collection)
            size = dim if dim is not None else embed_dim()
            from qdrant_client.models import Distance, VectorParams

            client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=size, distance=Distance.COSINE),
            )
            return ChunkOpResult(ok=True, status="created", detail=self.collection)
        except Exception as exc:  # noqa: BLE001 — degraded, reported
            return ChunkOpResult(
                ok=False,
                status="deferred",
                detail=f"{type(exc).__name__}: {exc}",
            )

    # --- writes
    def upsert(
        self, chunks: list[ChunkRecord], doc_id: str, group_id: str | None = None
    ) -> ChunkOpResult:
        """Embed and upsert the chunks of one document."""
        if not self.enabled:
            return ChunkOpResult(ok=True, status="disabled", count=len(chunks))
        if not chunks:
            return ChunkOpResult(ok=True, status="skipped", detail="no chunks")
        try:
            from qdrant_client.models import PointStruct

            vectors = embed_texts([c.text for c in chunks])
            now = datetime.now(UTC).isoformat()
            points = [
                PointStruct(
                    id=chunk_point_id(doc_id, c.index),
                    vector=vec,
                    payload={
                        "doc_id": doc_id,
                        "group_id": group_id,
                        "chunk_id": c.chunk_id,
                        "index": c.index,
                        "start": c.start,
                        "end": c.end,
                        "text": c.text,
                        "created_at": now,
                        "deleted": False,
                        "superseded": False,
                    },
                )
                for c, vec in zip(chunks, vectors, strict=True)
            ]
            self._client_or_raise().upsert(
                collection_name=self.collection, wait=True, points=points
            )
            return ChunkOpResult(ok=True, status="synced", count=len(points))
        except Exception as exc:  # noqa: BLE001 — degraded, reported
            return ChunkOpResult(
                ok=False,
                status="deferred",
                detail=f"{type(exc).__name__}: {exc}",
            )

    # --- soft flags (delete / supersede a document's chunks)
    def flag_doc(self, doc_id: str, **flags: Any) -> ChunkOpResult:
        """Soft-flag every chunk of one document (nothing is removed)."""
        if not self.enabled:
            return ChunkOpResult(ok=True, status="disabled")
        if not flags:
            return ChunkOpResult(ok=True, status="skipped", detail="no flags")
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            self._client_or_raise().set_payload(
                collection_name=self.collection,
                wait=True,
                payload=flags,
                points=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                ),
            )
            return ChunkOpResult(ok=True, status="flagged", detail=doc_id)
        except Exception as exc:  # noqa: BLE001 — degraded, reported
            return ChunkOpResult(
                ok=False,
                status="deferred",
                detail=f"{type(exc).__name__}: {exc}",
            )

    # --- search
    def search(
        self,
        vector: list[float],
        limit: int | None = None,
        group_id: str | None = None,
        doc_id: str | None = None,
        include_deleted: bool = False,
        include_superseded: bool = False,
    ) -> ChunkOpResult:
        """Vector search over chunks, with soft-flag filtering.

        A missing collection is not an error: it simply means no chunk has
        been ingested yet, so this returns an empty (disabled) result instead
        of surfacing a Qdrant 404.
        """
        if not self.enabled:
            return ChunkOpResult(ok=True, status="disabled", count=0)
        limit = self._settings.vector_default_limit if limit is None else limit
        try:
            client = self._client_or_raise()
            if not client.collection_exists(self.collection):
                return ChunkOpResult(
                    ok=True,
                    status="missing",
                    detail=f"collection '{self.collection}' not created yet",
                    count=0,
                )
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            must: list[Any] = []
            must_not: list[Any] = []
            if group_id:
                must.append(
                    FieldCondition(key="group_id", match=MatchValue(value=group_id))
                )
            if doc_id:
                must.append(
                    FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
                )
            if not include_deleted:
                must_not.append(
                    FieldCondition(key="deleted", match=MatchValue(value=True))
                )
            if not include_superseded:
                must_not.append(
                    FieldCondition(key="superseded", match=MatchValue(value=True))
                )
            points = (
                client.query_points(
                    collection_name=self.collection,
                    query=vector,
                    query_filter=Filter(must=must or None, must_not=must_not or None),
                    with_payload=True,
                    limit=limit,
                )
                .points
            )
            return ChunkOpResult(
                ok=True, status="ok", count=len(points), data={"points": points}
            )
        except Exception as exc:  # noqa: BLE001 — degraded, reported
            return ChunkOpResult(
                ok=False,
                status="deferred",
                detail=f"{type(exc).__name__}: {exc}",
            )


_CHUNK_STORE: ChunkStore | None = None


def get_chunk_store(settings: Settings | None = None) -> ChunkStore:
    """Process-wide chunk store singleton."""
    global _CHUNK_STORE
    if _CHUNK_STORE is None:
        _CHUNK_STORE = ChunkStore(settings)
    return _CHUNK_STORE


def reset_chunk_store() -> None:
    global _CHUNK_STORE
    _CHUNK_STORE = None
