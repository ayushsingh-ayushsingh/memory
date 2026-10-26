"""Per-user memory over the DUL graph (FalkorDB) + Qdrant.

Every user's data is isolated by a DUL ``group`` key of the form
``user:{user_id}``. That group is stamped on every FalkorDB edge (``group_id``)
and every Qdrant payload/point-id, so one user can never read another's facts.
The group is always derived server-side from the verified JWT ``sub`` — clients
never supply it.

Two operations back the chat loop:

- :func:`search_context` — retrieve the user's most relevant facts for a prompt
  and hand them to the conductor as a TOON "Extracted context" block.
- :func:`ingest_exchange` — after a turn, coreference-resolve the combined text,
  extract DUL-checked relations, chunk + embed, and write into the user's group.
"""

from __future__ import annotations

import logging
from typing import Any

from .toon_utils import toon

logger = logging.getLogger(__name__)

# Upper bound of retrieved facts handed to the agent per prompt.
CONTEXT_LIMIT = 10


def user_group(user_id: str) -> str:
    """DUL partition key for one user. The single source of isolation."""
    return f"user:{user_id}"


async def _session() -> Any:
    # Imported lazily: dul_graph_rag pulls in torch/spacy and must not load
    # until a chat request actually needs it.
    from dul_graph_rag.api import HOLDER

    return await HOLDER.get()


async def search_context(
    user_id: str, query: str, limit: int = CONTEXT_LIMIT
) -> str:
    """Retrieve the user's top facts for ``query`` as a TOON block.

    Returns ``""`` when nothing is found so the caller can fall back to the
    bare prepended prompt. Dates in the hits are naturalized before TOON.
    """
    session = await _session()
    try:
        from dul_graph_rag.modules.crud import manual_search

        report = await manual_search(
            session.graphiti,
            session.deps,
            query,
            limit=limit,
            group=user_group(user_id),
        )
    except Exception as exc:  # noqa: BLE001 — memory must never break a reply
        logger.warning("graph search failed for user memory: %s", exc)
        return ""

    hits = getattr(report, "hits", None) or []
    if not hits:
        return ""

    payload = {
        "hits": [
            {
                "fact": h.fact,
                "score": round(h.score, 4),
                "when": h.created_at,
            }
            for h in hits
        ]
    }
    return toon(payload)


async def ingest_exchange(
    user_id: str, text: str, *, conversation_id: str | None = None
) -> dict[str, Any] | None:
    """Coref-resolve, extract relations, chunk + embed ``text`` into the group.

    Runs in the background after a reply so the user never waits on it. Any
    failure is logged and swallowed — a memory write must never break the chat.
    """
    if not text.strip():
        return None
    session = await _session()
    try:
        from dul_graph_rag.modules.longtext import extract_long_text

        return await extract_long_text(
            text,
            session=session,
            group=user_group(user_id),
            doc_id=conversation_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory ingestion failed for user %s: %s", user_id, exc)
        return None


async def wipe_user_memory(user_id: str) -> dict[str, Any]:
    """Hard-delete every FalkorDB edge + Qdrant point for one user's group."""
    session = await _session()
    from dul_graph_rag.modules.crud import manual_reset_group

    return await manual_reset_group(session.graphiti, group=user_group(user_id))


async def wipe_conversation_memory(
    user_id: str, conversation_id: str
) -> dict[str, Any]:
    """Soft-delete every fact/chunk learned from one conversation.

    Memory is written with ``doc_id=conversation_id`` at ingest time, so this
    flags exactly the facts sourced from that chat — nothing else in the user's
    group is touched.
    """
    session = await _session()
    from dul_graph_rag.modules.crud import manual_bulk_delete_docs

    return await manual_bulk_delete_docs(
        session.graphiti, [conversation_id], group=user_group(user_id)
    )


# %% ── Fact CRUD (scoped to one user's group) ────────────────────────────────
# Thin, tool-friendly wrappers over the DUL facade. Every call is stamped with
# ``user_group(user_id)`` so a conductor tool can never touch another user's
# facts. Soft-update / soft-delete return the ``fact_key`` an agent uses as its
# id for a later edit.


def _build_triple(
    *,
    subject_name: str,
    relation: str,
    object_name: str,
    subject_class: str | None = None,
    object_class: str | None = None,
    relation_name: str = "",
    fact_sentence: str = "",
    subject_id: str | None = None,
    object_id: str | None = None,
) -> dict[str, Any]:
    from dul_graph_rag.api import TripleRequest, _resolve_triple

    req = TripleRequest(
        subject_id=subject_id,
        subject_name=subject_name,
        subject_class=subject_class,
        relation=relation,
        relation_name=relation_name,
        object_id=object_id,
        object_name=object_name,
        object_class=object_class,
        fact_sentence=fact_sentence,
        source="agent",
    )
    # _resolve_triple raises HTTPException for bad DUL terms; surface a plain
    # ValueError so a tool can report it to the model instead of a 500.
    return _resolve_triple(req, _deps())


def _deps() -> dict[str, Any]:
    from dul_graph_rag.modules.deps import get_jev_deps

    return get_jev_deps()


async def create_fact(
    user_id: str,
    *,
    subject_name: str,
    relation: str,
    object_name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create one DUL fact. Returns ``{status, fact_key}`` — the id for edits."""
    session = await _session()
    from dul_graph_rag.modules.crud import manual_create_triple

    triple = _build_triple(
        subject_name=subject_name,
        relation=relation,
        object_name=object_name,
        **kwargs,
    )
    return await manual_create_triple(
        session.graphiti, session.deps, triple, group=user_group(user_id)
    )


async def update_fact(
    user_id: str,
    *,
    subject_name: str,
    relation: str,
    object_name: str,
    supersedes: list[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Soft-supersede prior value(s) and write the new version. Returns new id."""
    session = await _session()
    from dul_graph_rag.modules.crud import manual_update_triple

    triple = _build_triple(
        subject_name=subject_name,
        relation=relation,
        object_name=object_name,
        **kwargs,
    )
    return await manual_update_triple(
        session.graphiti,
        session.deps,
        triple,
        group=user_group(user_id),
        supersedes=supersedes or None,
    )


async def delete_fact(user_id: str, fact_key: str) -> dict[str, Any]:
    """Soft-delete one fact by its id. Nothing is hard-removed."""
    session = await _session()
    from dul_graph_rag.modules.crud import manual_delete_triple

    return await manual_delete_triple(
        session.graphiti, fact_key, group=user_group(user_id)
    )


async def bulk_create_facts(
    user_id: str, triples: list[dict[str, Any]]
) -> dict[str, Any]:
    """Create many facts. Each dict needs subject_name/relation/object_name."""
    session = await _session()
    from dul_graph_rag.modules.crud import manual_bulk_create

    built = [_build_triple(**t) for t in triples]
    return await manual_bulk_create(
        session.graphiti, session.deps, built, group=user_group(user_id)
    )


async def bulk_delete_facts(user_id: str, fact_keys: list[str]) -> dict[str, Any]:
    """Soft-delete many facts by id."""
    session = await _session()
    from dul_graph_rag.modules.crud import manual_bulk_delete

    return await manual_bulk_delete(
        session.graphiti, fact_keys, group=user_group(user_id)
    )


async def list_facts(user_id: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search the user's facts, returning id + sentence for the agent."""
    session = await _session()
    from dul_graph_rag.modules.crud import manual_search

    report = await manual_search(
        session.graphiti, session.deps, query, limit=limit, group=user_group(user_id)
    )
    return [
        {"fact_key": h.ref, "fact": h.fact, "score": round(h.score, 4)}
        for h in report.hits
    ]


__all__ = [
    "CONTEXT_LIMIT",
    "bulk_create_facts",
    "bulk_delete_facts",
    "create_fact",
    "delete_fact",
    "ingest_exchange",
    "list_facts",
    "search_context",
    "update_fact",
    "user_group",
    "wipe_conversation_memory",
    "wipe_user_memory",
]
