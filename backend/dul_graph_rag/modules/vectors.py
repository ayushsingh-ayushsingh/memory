from __future__ import annotations

import uuid
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from .embeddings import embed_dim, embed_texts
from .settings import S, Settings, get_settings


# %% Cell 12 — QDRANT VECTOR MIRROR (resilient by design)
#
# The graph (FalkorDB) is the system of record; this mirror is an
# *acceleration structure* for semantic search. So a Qdrant outage must never
# destroy or block a graph write. Every operation returns a `VectorOpResult`
# instead of raising:
#
#   synced   -> vectors written
#   skipped  -> mirror disabled or empty payload
#   deferred -> mirror unreachable; the facts are in the graph, replay with
#               sync_vectors() when Qdrant is back
#   failed   -> mirror reachable but the operation failed
#
# Set DUL_VECTOR_MIRROR_REQUIRED=true to flip to fail-closed behaviour (a
# write is rejected when the mirror is down).


class VectorStoreError(RuntimeError):
    """The mirror is reachable but the operation failed."""


class VectorStoreUnavailable(RuntimeError):
    """The mirror cannot be reached (connection refused / timeout)."""


class VectorOpResult(BaseModel):
    """Outcome of one mirror operation."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    status: str
    detail: str = ""
    count: int = 0
    data: dict[str, Any] = Field(default_factory=dict)


class VectorPoint(BaseModel):
    """One fact vector to store in the mirror."""

    model_config = ConfigDict(extra="forbid")

    key: str
    vector: list[float]
    payload: dict[str, Any] = Field(default_factory=dict)
    group: str | None = Field(
        default=None,
        description="Logical partition; part of the point id so groups never collide",
    )
    version: int = Field(
        default=0,
        ge=0,
        description="0 = base write; n = superseding rewrite (separate point id)",
    )


def fact_point_id(
    fact_key: str, group: str | None = None, version: int = 0
) -> str:
    """Deterministic UUID for a fact key (stable across re-runs).

    The group is part of the identity: two logical partitions may hold the
    same fact key, and they must not overwrite each other's vector.

    ``version`` (default 0) is appended to the scope so an *update* writes a
    fresh point instead of silently overwriting the old one.  The old point is
    then flagged ``superseded`` (soft) and de-weighted in search.
    """
    scope = f"dul-fact:{group}:{fact_key}" if group else f"dul-fact:{fact_key}"
    if version:
        scope = f"{scope}#v{version}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, scope))


def versioned_key(fact_key: str, version: int) -> str:
    """``(key, 0)`` is the legacy key; ``>0`` appends ``#v{n}``."""
    return fact_key if not version else f"{fact_key}#v{version}"


class VectorMirror:
    """Thin, failure-tolerant wrapper around the Qdrant client."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any = None
        self._ensured = False
        self._last_error: str | None = None

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def collection(self) -> str:
        return self._settings.fact_collection

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

    def _unavailable(self, exc: Exception) -> Exception:
        return VectorStoreUnavailable(
            f"qdrant unreachable at {self._settings.qdrant_url}: "
            f"{type(exc).__name__}: {exc}"
        )

    def _guard_required(self, exc: Exception) -> None:
        """Fail-closed mode: the mirror outage must abort the write."""
        if self._settings.vector_mirror_required:
            raise self._unavailable(exc)

    # --- health
    def available(self) -> bool:
        """Is the mirror reachable right now? (cheap probe, result cached)"""
        try:
            self._client_or_raise().get_collections()
            self._last_error = None
            return True
        except Exception as exc:  # noqa: BLE001 — availability probe
            self._last_error = f"{type(exc).__name__}: {exc}"
            return False

    def status(self) -> VectorOpResult:
        """Structured availability snapshot (never raises)."""
        if not self.enabled:
            return VectorOpResult(
                ok=True, status="disabled", detail="vector mirror disabled by settings"
            )
        try:
            client = self._client_or_raise()
            names = [c.name for c in client.get_collections().collections]
            self._last_error = None
            points = (
                client.count(self.collection, exact=True).count
                if self.collection in names
                else 0
            )
            return VectorOpResult(
                ok=True,
                status="up",
                detail=f"{self.collection}: {points} points",
                count=points,
                data={"collections": names},
            )
        except Exception as exc:  # noqa: BLE001 — reported as unreachable
            self._last_error = f"{type(exc).__name__}: {exc}"
            return VectorOpResult(
                ok=False,
                status="unreachable",
                detail=self._last_error,
                data={"url": self._settings.qdrant_url},
            )

    # --- collection
    def ensure_collection(self, dim: int | None = None) -> VectorOpResult:
        """Create the fact collection if needed; validate its vector size."""
        if not self.enabled:
            return VectorOpResult(ok=True, status="disabled")
        try:
            client = self._client_or_raise()
            if client.collection_exists(self.collection):
                info = client.get_collection(self.collection)
                size = _collection_size(info)
                if dim is not None and size is not None and size != dim:
                    raise VectorStoreError(
                        f"collection '{self.collection}' has vector size {size}, "
                        f"but the configured embedding model produces {dim}. "
                        "Re-create the collection or change DUL_DENSE_MODEL."
                    )
                self._ensured = True
                return VectorOpResult(
                    ok=True, status="exists", detail=f"{self.collection} (size {size})"
                )
            size = dim if dim is not None else embed_dim()
            from qdrant_client.models import Distance, VectorParams

            client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=size, distance=Distance.COSINE),
            )
            self._ensured = True
            return VectorOpResult(
                ok=True, status="created", detail=f"{self.collection} (size {size})"
            )
        except Exception as exc:  # noqa: BLE001 — degraded, never fatal here
            self._guard_required(exc)
            return VectorOpResult(
                ok=False,
                status="deferred",
                detail=f"{type(exc).__name__}: {exc}",
            )

    # --- writes
    def upsert(self, points: list[VectorPoint]) -> VectorOpResult:
        """Upsert fact vectors; point ids are derived from (group, fact key)."""
        if not self.enabled:
            return VectorOpResult(ok=True, status="disabled", count=len(points))
        if not points:
            return VectorOpResult(ok=True, status="skipped", detail="nothing to write")
        try:
            from qdrant_client.models import PointStruct

            client = self._client_or_raise()
            client.upsert(
                collection_name=self.collection,
                wait=True,
                points=[
                    PointStruct(
                        id=fact_point_id(p.key, p.group, p.version),
                        vector=p.vector,
                        payload=p.payload,
                    )
                    for p in points
                ],
            )
            return VectorOpResult(ok=True, status="synced", count=len(points))
        except Exception as exc:  # noqa: BLE001 — degraded, reported
            self._guard_required(exc)
            return VectorOpResult(
                ok=False,
                status="deferred",
                detail=f"{type(exc).__name__}: {exc}",
                count=0,
            )

    def delete(self, keys: list[str], group: str | None = None) -> VectorOpResult:
        """Delete fact vectors by fact key (optionally scoped to a group)."""
        if not self.enabled:
            return VectorOpResult(ok=True, status="disabled", count=len(keys))
        if not keys:
            return VectorOpResult(ok=True, status="skipped", detail="nothing to delete")
        try:
            from qdrant_client.models import PointIdsList

            self._client_or_raise().delete(
                collection_name=self.collection,
                wait=True,
                points_selector=PointIdsList(
                    points=[fact_point_id(k, group) for k in keys]
                ),
            )
            return VectorOpResult(ok=True, status="synced", count=len(keys))
        except Exception as exc:  # noqa: BLE001 — degraded, reported
            self._guard_required(exc)
            return VectorOpResult(
                ok=False,
                status="deferred",
                detail=f"{type(exc).__name__}: {exc}",
                count=0,
            )

    def flag(
        self,
        keys: list[str],
        group: str | None = None,
        version: int = 0,
        **payload: Any,
    ) -> VectorOpResult:
        """Soft-flag points (``deleted``/``superseded``/``superseded_by``/...).

        Uses Qdrant ``set_payload`` so nothing is physically removed; the
        flags only change the point's search weight.  Returns the number of
        points actually flagged.
        """
        if not self.enabled:
            return VectorOpResult(ok=True, status="disabled", count=len(keys))
        if not keys:
            return VectorOpResult(ok=True, status="skipped", detail="nothing to flag")
        if not payload:
            return VectorOpResult(ok=True, status="skipped", detail="no flags given")
        try:
            from qdrant_client.models import PointIdsList

            ids = [fact_point_id(k, group, version) for k in keys]
            self._client_or_raise().set_payload(
                collection_name=self.collection,
                wait=True,
                payload=payload,
                points=PointIdsList(points=ids),
            )
            return VectorOpResult(ok=True, status="flagged", count=len(ids))
        except Exception as exc:  # noqa: BLE001 — degraded, reported
            self._guard_required(exc)
            return VectorOpResult(
                ok=False,
                status="deferred",
                detail=f"{type(exc).__name__}: {exc}",
                count=0,
            )

    def flag_by_doc(self, doc_id: str, group: str | None = None, **payload: Any) -> VectorOpResult:
        """Soft-flag every fact point whose ``doc_id`` matches (best-effort)."""
        if not self.enabled:
            return VectorOpResult(ok=True, status="disabled")
        if not payload:
            return VectorOpResult(ok=True, status="skipped", detail="no flags")
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            must: list[Any] = [
                FieldCondition(key="doc_id", match=MatchValue(value=doc_id))
            ]
            if group:
                must.append(
                    FieldCondition(key="group_id", match=MatchValue(value=group))
                )
            self._client_or_raise().set_payload(
                collection_name=self.collection,
                wait=True,
                payload=payload,
                points=Filter(must=must),
            )
            return VectorOpResult(ok=True, status="flagged", detail=doc_id)
        except Exception as exc:  # noqa: BLE001 — degraded, reported
            self._guard_required(exc)
            return VectorOpResult(
                ok=False,
                status="deferred",
                detail=f"{type(exc).__name__}: {exc}",
                count=0,
            )

    def wipe_group(self, group: str) -> VectorOpResult:
        """Delete every point belonging to one logical group (reset path)."""
        if not self.enabled:
            return VectorOpResult(ok=True, status="disabled")
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            client = self._client_or_raise()
            ids: list[Any] = []
            offset: Any = None
            while True:
                points, offset = client.scroll(
                    collection_name=self.collection,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(key="group_id", match=MatchValue(value=group))
                        ]
                    ),
                    limit=self._settings.scroll_page_size,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                ids.extend([p.id for p in points])
                if offset is None:
                    break
            if ids:
                client.delete(
                    collection_name=self.collection, wait=True, points_selector=ids
                )
            return VectorOpResult(
                ok=True,
                status="synced",
                count=len(ids),
                detail=f"{len(ids)} vectors removed from group '{group}'",
            )
        except Exception as exc:  # noqa: BLE001 — the graph wipe already succeeded
            self._guard_required(exc)
            return VectorOpResult(
                ok=False,
                status="deferred",
                detail=f"{type(exc).__name__}: {exc}",
                count=0,
            )

    # --- reads
    def search(
        self,
        vector: list[float],
        limit: int | None = None,
        group_id: str | None = None,
        include_deleted: bool = False,
        include_superseded: bool = False,
    ) -> VectorOpResult:
        """Vector search, optionally filtered to one logical group.

        Soft-flagged points (``deleted``/``superseded`` in the payload) are
        excluded unless explicitly requested.  Flags are stored on the point
        payload at write time, so this is a plain server-side filter.
        """
        if not self.enabled:
            return VectorOpResult(ok=True, status="disabled", count=0)
        limit = self._settings.vector_default_limit if limit is None else limit
        try:
            from qdrant_client.models import (
                FieldCondition,
                Filter,
                MatchValue,
            )

            must: list[Any] = []
            must_not: list[Any] = []
            if group_id:
                must.append(
                    FieldCondition(key="group_id", match=MatchValue(value=group_id))
                )
            if not include_deleted:
                # keep points where `deleted` is absent OR explicitly False
                must_not.append(
                    FieldCondition(key="deleted", match=MatchValue(value=True))
                )
            if not include_superseded:
                must_not.append(
                    FieldCondition(key="superseded", match=MatchValue(value=True))
                )
            query_filter = Filter(must=must or None, must_not=must_not or None)
            points = (
                self._client_or_raise()
                .query_points(
                    collection_name=self.collection,
                    query=vector,
                    query_filter=query_filter,
                    with_payload=True,
                    limit=limit,
                )
                .points
            )
            return VectorOpResult(
                ok=True, status="ok", count=len(points), data={"points": points}
            )
        except Exception as exc:  # noqa: BLE001 — degraded, reported
            self._guard_required(exc)
            return VectorOpResult(
                ok=False,
                status="deferred",
                detail=f"{type(exc).__name__}: {exc}",
                count=0,
            )

    def existing_fact_keys(self, group: str | None = None) -> set[str]:
        """Fact keys currently present in the mirror (optionally group-scoped)."""
        if not self.enabled:
            return set()
        try:
            client = self._client_or_raise()
            keys: set[str] = set()
            offset: Any = None
            while True:
                points, offset = client.scroll(
                    collection_name=self.collection,
                    limit=self._settings.scroll_page_size,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for p in points:
                    payload = p.payload or {}
                    if group is not None and payload.get("group_id") != group:
                        continue
                    key = payload.get("fact_key")
                    if key:
                        keys.add(str(key))
                if offset is None:
                    break
            return keys
        except Exception as exc:  # noqa: BLE001 — degraded, reported
            self._guard_required(exc)
            return set()

    # --- backfill
    def sync_missing(
        self, facts: list[tuple[str, str]], group: str | None = None
    ) -> VectorOpResult:
        """Upsert only the facts whose key is missing from the mirror.

        `facts` is a list of `(fact_key, fact_text)` pairs taken from the
        graph (system of record). Used to replay writes that happened while
        the mirror was down.
        """
        if not self.enabled:
            return VectorOpResult(ok=True, status="disabled")
        if not facts:
            return VectorOpResult(ok=True, status="skipped", detail="nothing to sync")
        present = self.existing_fact_keys(group)
        missing = [(k, t) for k, t in facts if k not in present]
        if not missing:
            return VectorOpResult(
                ok=True, status="synced", count=0, detail="mirror already complete"
            )
        vectors = embed_texts([t for _k, t in missing])
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        result = self.upsert(
            [
                VectorPoint(
                    key=k,
                    vector=vec,
                    payload={
                        "fact_key": k,
                        "fact_sentence": t,
                        "group_id": group,
                        "version": 0,
                        "created_at": now,
                        "deleted": False,
                        "superseded": False,
                    },
                    group=group,
                )
                for (k, t), vec in zip(missing, vectors, strict=True)
            ]
        )
        result.detail = (
            f"backfilled {result.count}/{len(missing)} missing vectors"
            if result.ok
            else result.detail
        )
        result.data["missing"] = [k for k, _t in missing]
        return result

    # --- maintenance
    def prune_stale(self) -> VectorOpResult:
        """Delete points whose id no longer matches the current derivation.

        Keeps the mirror clean after an id-scheme change (e.g. adding the
        group scope to the point id).
        """
        if not self.enabled:
            return VectorOpResult(ok=True, status="disabled")
        try:
            client = self._client_or_raise()
            stale: list[str] = []
            offset: Any = None
            while True:
                points, offset = client.scroll(
                    collection_name=self.collection,
                    limit=self._settings.scroll_page_size,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for p in points:
                    payload = p.payload or {}
                    key = payload.get("fact_key")
                    if not key:
                        stale.append(str(p.id))
                        continue
                    expected = fact_point_id(
                        str(key), payload.get("group_id"), int(payload.get("version") or 0)
                    )
                    if str(p.id) != expected:
                        stale.append(str(p.id))
                if offset is None:
                    break
            if stale:
                from qdrant_client.models import PointIdsList

                client.delete(
                    collection_name=self.collection,
                    wait=True,
                    points_selector=PointIdsList(points=stale),
                )
            return VectorOpResult(
                ok=True,
                status="pruned",
                count=len(stale),
                detail=f"{len(stale)} stale points removed",
            )
        except Exception as exc:  # noqa: BLE001 — degraded, reported
            self._guard_required(exc)
            return VectorOpResult(
                ok=False, status="deferred", detail=f"{type(exc).__name__}: {exc}"
            )


def _collection_size(info: Any) -> int | None:
    """Vector size of an existing collection (None if it is not a named vector)."""
    params = getattr(info, "config", None)
    vectors = getattr(params, "params", None)
    vectors = getattr(vectors, "vectors", None)
    if isinstance(vectors, dict):  # named vectors
        first = next(iter(vectors.values()), None)
        return getattr(first, "size", None)
    return getattr(vectors, "size", None)


_MIRROR: VectorMirror | None = None


def get_mirror(settings: Settings | None = None) -> VectorMirror:
    """Process-wide mirror singleton."""
    global _MIRROR
    if _MIRROR is None:
        _MIRROR = VectorMirror(settings)
    return _MIRROR


def reset_mirror() -> None:
    """Drop the singleton (settings changed)."""
    global _MIRROR
    _MIRROR = None



def delete_fact(
    fact_key: str, group: str | None = None, version: int = 0
) -> VectorOpResult:
    """Soft-delete one fact vector by fact key (flags it, does not remove it)."""
    from datetime import UTC, datetime

    return get_mirror().flag(
        [fact_key],
        group=group,
        version=version,
        deleted=True,
        deleted_at=datetime.now(UTC).isoformat(),
    )


def flag_fact(fact_key: str, group: str | None = None, **payload: Any) -> VectorOpResult:
    """Set arbitrary soft flags on one fact vector."""
    return get_mirror().flag([fact_key], group=group, **payload)


def search_facts(
    vector: list[float],
    limit: int | None = None,
    group_id: str | None = None,
    include_deleted: bool = False,
    include_superseded: bool = False,
) -> VectorOpResult:
    """Vector search over the fact mirror (server-side group + flag filters)."""
    limit = S.vector_default_limit if limit is None else limit
    return get_mirror().search(
        vector,
        limit=limit,
        group_id=group_id,
        include_deleted=include_deleted,
        include_superseded=include_superseded,
    )
