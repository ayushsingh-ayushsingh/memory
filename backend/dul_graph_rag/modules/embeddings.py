from __future__ import annotations

from typing import Any

from .settings import S


# %% Cell 13 — EMBEDDINGS + RERANKER (local fastembed, no API key)
#
# Both models are local `fastembed` models, so the notebook works offline for
# everything except Groq (extraction) and Jev (mapping). The embedder is also
# what Graphiti uses for its own edges, so the graph and the mirror speak the
# same vector space. Model ids come from .env (DUL_DENSE_MODEL /
# DUL_RERANK_MODEL), never from a literal here.

# Graphiti's own client ABCs: the notebook's embedder/reranker implement them,
# so Graphiti can be handed these local, key-less implementations.
from graphiti_core.cross_encoder import CrossEncoderClient as _CrossEncoderClient
from graphiti_core.embedder import EmbedderClient as _EmbedderClient

_EMBEDDING_MODEL: Any = None
_RERANKER: Any = None


def get_embedding_model() -> Any:
    """fastembed TextEmbedding; downloads the model on first use."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        from fastembed import TextEmbedding

        _EMBEDDING_MODEL = TextEmbedding(model_name=S.dense_model)
    return _EMBEDDING_MODEL


def get_reranker() -> Any:
    """fastembed cross-encoder reranker (jina v2 multilingual by default)."""
    global _RERANKER
    if _RERANKER is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        _RERANKER = TextCrossEncoder(model_name=S.rerank_model)
    return _RERANKER


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts (dense model from settings)."""
    model = get_embedding_model()
    return [vec.tolist() for vec in model.embed(texts)]


def embed_dim() -> int:
    """Dimension of the configured dense model."""
    return len(embed_texts(["dimension probe"])[0])


def rerank_scores(query: str, documents: list[str]) -> list[float]:
    """Cross-encoder relevance of every document for the query."""
    return list(get_reranker().rerank(query, documents))


class FastEmbedEmbedder(_EmbedderClient):
    """Graphiti `EmbedderClient` backed by local fastembed."""

    async def create(self, input_data: str | list[str] | Any) -> list[float]:
        texts = [input_data] if isinstance(input_data, str) else list(input_data)
        return embed_texts(texts)[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        return embed_texts(list(input_data_list))


class JinaCrossEncoder(_CrossEncoderClient):
    """Graphiti `CrossEncoderClient` backed by the local jina reranker."""

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        scores = rerank_scores(query, list(passages))
        return sorted(zip(passages, scores), key=lambda pair: pair[1], reverse=True)
