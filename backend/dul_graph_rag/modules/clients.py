from __future__ import annotations

import re
from typing import Any

from .embeddings import FastEmbedEmbedder, JinaCrossEncoder
from .settings import S


# %% Cell 14 — GRAPHITI SETUP (FalkorDB + Groq client + local fastembed)
#
# Every endpoint, store name, model id and group id comes from the Settings
# cell — this cell only wires them together. The FalkorDriver subclass
# translates Graphiti's index DDL into this server's dialect, because this
# FalkorDB build cannot run the `CREATE INDEX ... IF NOT EXISTS (FOR ...)`
# form Graphiti emits.

_GROQ_API_KEY: str | None = None
_GRAPHITI: Any = None


def groq_api_key() -> str:
    """Groq key from the environment / project .env (never hardcoded)."""
    key = (S.groq_api_key or "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY missing: add it to the project .env file")
    return key


def get_llm() -> Any:
    """Graphiti's LLM client. Only ever used if Graphiti itself extracts; the
    Jev pipeline writes LLM-free, so this is wiring, not a cost."""
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.groq_client import GroqClient

    return GroqClient(
        config=LLMConfig(
            api_key=groq_api_key(),
            model=S.groq_model,
            temperature=S.groq_temperature,
            max_tokens=S.groq_max_tokens,
        )
    )


def get_embedder() -> Any:
    """Local fastembed embedder handed to Graphiti."""
    return FastEmbedEmbedder()


def get_cross_encoder() -> Any:
    """Local jina reranker handed to Graphiti."""
    return JinaCrossEncoder()


# %% FalkorDB dialect compatibility
_RANGE_RE = re.compile(r"CREATE INDEX \S+ IF NOT EXISTS (FOR .*)$")
_FT_PROC_RE = re.compile(
    r"CALL db\.idx\.fulltext\.createNodeIndex\(\s*\{\s*label:\s*'([^']+)'.*?\}\s*,\s*(.*)\)\s*$",
    re.DOTALL,
)
_FT_FIELDS_RE = re.compile(r"'([^']+)'")
_ALREADY_INDEXED = ("already indexed", "already exists", "equivalent")


def _translate_index_query(query: str) -> str:
    """Rewrite Graphiti DDL into this server's dialect (derived at runtime)."""
    m = _RANGE_RE.match(query.strip())
    if m:
        return f"CREATE INDEX {m.group(1)}"
    m = _FT_PROC_RE.match(query.strip())
    if m:
        label, fields_blob = m.group(1), m.group(2)
        fields = ", ".join(f"n.{f}" for f in _FT_FIELDS_RE.findall(fields_blob))
        return f"CREATE FULLTEXT INDEX FOR (n:{label}) ON ({fields})"
    return query


async def get_graphiti() -> Any:
    """Build (once) Graphiti on the configured FalkorDB store; create indices."""
    global _GRAPHITI
    if _GRAPHITI is not None:
        return _GRAPHITI
    from graphiti_core import Graphiti
    from graphiti_core.driver.falkordb_driver import FalkorDriver
    from graphiti_core.graph_queries import get_fulltext_indices, get_range_indices

    class CompatFalkorDriver(FalkorDriver):
        def clone(self, database: str) -> Any:
            """Preserve the dialect override across Graphiti's per-group clones."""
            if database == self._database:
                return self
            return CompatFalkorDriver(falkor_db=self.client, database=database)

        async def build_indices_and_constraints(
            self, delete_existing: bool = False
        ) -> None:
            if delete_existing:
                raise RuntimeError("delete_existing not supported on this server build")
            queries = get_range_indices(self.provider) + get_fulltext_indices(
                self.provider
            )
            for query in queries:
                try:
                    await self.execute_query(_translate_index_query(str(query)))
                except Exception as exc:  # noqa: BLE001 — "already indexed" is fine
                    if any(s in str(exc).lower() for s in _ALREADY_INDEXED):
                        continue
                    raise

    driver = CompatFalkorDriver(
        host=S.falkordb_host,
        port=S.falkordb_port,
        username=S.falkordb_user,
        password=S.falkordb_password,
        database=S.graphiti_graph,
    )
    _GRAPHITI = Graphiti(
        graph_driver=driver,
        llm_client=get_llm(),
        embedder=get_embedder(),
        cross_encoder=get_cross_encoder(),
    )
    await _GRAPHITI.build_indices_and_constraints()
    return _GRAPHITI


async def close_graphiti() -> None:
    """Close the Graphiti singleton (called by the teardown cell)."""
    global _GRAPHITI
    if _GRAPHITI is not None:
        await _GRAPHITI.close()
        _GRAPHITI = None
