from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from .settings import S


# %% Cell 06 — GRAPH STORES: which FalkorDB graph holds what, and who owns it
#
# There are **two** graphs in FalkorDB and they are *not* interchangeable —
# they have incompatible node/edge contracts:
#
#   store     nodes                      edges                    owner
#   --------  -------------------------  -----------------------  -------------
#   graphiti  :Entity (+ DUL label)      :RELATES_TO (name=DUL)   this notebook
#   legacy    :Resource (+ DUL labels)   typed (:hasParticipant)  main.py bench
#
# The legacy pipeline drops and recreates its own graph on every run, so
# pointing both pipelines at one graph would delete Graphiti's data. They stay
# separate on purpose; the cell below is the single place that knows which is
# which. Names come from settings, never from literals.


class GraphStore(BaseModel):
    """One FalkorDB graph + its data contract."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Stable identifier used in code")
    graph: str = Field(description="FalkorDB graph name")
    owner: str = Field(description="Who writes this graph")
    node_labels: list[str] = Field(default_factory=list)
    edge_types: list[str] = Field(default_factory=list)
    wipe_policy: str = Field(default="never")
    purpose: str = ""


def stores() -> list[GraphStore]:
    """All configured stores, in load order."""
    return [
        GraphStore(
            key="graphiti",
            graph=S.graphiti_graph,
            owner="graphiti_crud_jev_standalone.py (this file)",
            node_labels=["Entity"],
            edge_types=["RELATES_TO"],
            wipe_policy="group-scoped (reset)",
            purpose=(
                "Graphiti temporal graph: Entity nodes + RELATES_TO edges, "
                "partitioned by group_id; mirrored to Qdrant vectors."
            ),
        ),
        GraphStore(
            key="legacy",
            graph=S.legacy_graph,
            owner="falkor.py (main.py notebook)",
            node_labels=["Resource"],
            edge_types=["typed DUL properties"],
            wipe_policy="dropped and recreated on every ingest run",
            purpose=(
                "Standalone DUL validation bench: Resource nodes with DUL class "
                "labels, symmetric mirrors and transitive closure materialised."
            ),
        ),
    ]


def describe_stores() -> list[dict[str, Any]]:
    """Notebook-ready rows describing every configured store."""
    return [
        {
            "store": st.key,
            "graph": st.graph,
            "nodes": ", ".join(st.node_labels) or "-",
            "edges": ", ".join(st.edge_types) or "-",
            "wipe policy": st.wipe_policy,
            "owner": st.owner,
        }
        for st in stores()
    ]
