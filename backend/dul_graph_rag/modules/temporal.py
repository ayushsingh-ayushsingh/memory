from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .settings import S


# %% Time-based flagging: recency decay + soft-flag weights
#
# Nothing is ever removed from the graph or the mirror. Instead every fact
# carries two soft flags (top-level Falkor edge props / Qdrant payload keys):
#
#   deleted_at    -> set by a delete; the fact is hidden by default
#   superseded_at -> set by an update; the old version is de-weighted
#
# Search weight = rerank_score x recency x flag_weight.
#   recency      = max(floor, 0.5 ** (age_days / half_life))
#   flag_weight  = deleted_weight if deleted, superseded_weight if superseded, else 1


def parse_ts(value: str | datetime | None) -> datetime | None:
    """Accept ISO strings (with/without tz) or datetimes; None if unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def age_days(created_at: str | datetime | None, now: datetime | None = None) -> float | None:
    """Whole/half days since creation; None if the timestamp is missing."""
    dt = parse_ts(created_at)
    if dt is None:
        return None
    now = now or datetime.now(UTC)
    return max(0.0, (now - dt).total_seconds() / 86400.0)


def recency_weight(created_at: str | datetime | None, now: datetime | None = None) -> float:
    """Half-life decay, floored so old data loses weight but never disappears."""
    days = age_days(created_at, now)
    if days is None:
        return 1.0  # no timestamp -> treat as fresh, do not punish
    return max(S.recency_floor, 0.5 ** (days / S.recency_half_life_days))


def flag_weight(
    deleted: bool = False,
    superseded: bool = False,
    include_deleted: bool = False,
    include_superseded: bool = False,
) -> float | None:
    """Multiplier for soft flags. Returns None when the hit must be dropped.

    Semantics:

    * **superseded** (an update replaced it) -> always shown, weighted by
      ``superseded_weight`` so old versions rank below the current one.  Set
      ``include_superseded=True`` to rank them at full weight instead.
    * **deleted** (a delete flagged it) -> weighted by ``deleted_weight``.
      With the default ``0`` the hit is dropped (hidden) from normal search;
      ``include_deleted=True`` re-includes it and, because you explicitly
      asked for it, ranks it by **recency** rather than multiplying it to 0
      (which would make every deleted hit tie at 0.0 and be unrankable).
    """
    weight = 1.0
    if superseded:
        if not include_superseded:
            weight *= S.superseded_weight
    if deleted:
        if include_deleted:
            pass  # explicitly requested: rank by recency, not by a 0 multiplier
        elif S.deleted_weight > 0:
            weight *= S.deleted_weight  # visible but de-weighted
        else:
            return None  # hidden by default
    return weight


def weighted_score(
    base: float,
    created_at: str | datetime | None,
    deleted: bool = False,
    superseded: bool = False,
    include_deleted: bool = False,
    include_superseded: bool = False,
    now: datetime | None = None,
) -> float | None:
    """base x recency x flag_weight; None means 'drop this hit'."""
    fw = flag_weight(
        deleted=deleted,
        superseded=superseded,
        include_deleted=include_deleted,
        include_superseded=include_superseded,
    )
    if fw is None:
        return None
    return float(base) * recency_weight(created_at, now) * fw


# %% Cypher helpers (FalkorDB) — flag edges without deleting anything
#
# All helpers match on `r.uuid` (the deterministic edge uuid from reports.edge_uuid)
# or on `r.fact_key` (used when the caller only knows the logical key).

async def flag_edge(
    driver: Any,
    uuid: str,
    group: str,
    **flags: Any,
) -> int:
    """Set soft-flag props on one edge. Returns the number of edges flagged.

    Only whitelisted props are written, so a caller cannot smuggle arbitrary
    Cypher into the SET clause.
    """
    allowed = {
        "deleted_at",
        "superseded_at",
        "superseded_by",
        "doc_id",
        "fact_key",
        "version",
    }
    clean = {k: v for k, v in flags.items() if k in allowed}
    if not clean:
        return 0
    set_clause = ", ".join(f"r.{k} = ${k}" for k in clean)
    rows, _, _ = await driver.execute_query(
        f"MATCH ()-[r:RELATES_TO]->() WHERE r.uuid = $u AND r.group_id = $g "
        f"SET {set_clause} RETURN count(r) AS n",
        u=uuid,
        g=group,
        **clean,
    )
    return int(rows[0].get("n", 0)) if rows else 0


async def flag_edges_by_key(
    driver: Any,
    fact_keys: list[str],
    group: str,
    **flags: Any,
) -> int:
    """Soft-flag every edge whose `fact_key` is in `fact_keys`. Returns count."""
    if not fact_keys:
        return 0
    allowed = {"deleted_at", "superseded_at", "superseded_by", "doc_id", "version"}
    clean = {k: v for k, v in flags.items() if k in allowed}
    set_clause = ", ".join(f"r.{k} = ${k}" for k in clean) or "r.uuid = r.uuid"
    rows, _, _ = await driver.execute_query(
        "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g AND r.fact_key IN $keys "
        f"SET {set_clause} RETURN count(r) AS n",
        g=group,
        keys=fact_keys,
        **clean,
    )
    return int(rows[0].get("n", 0)) if rows else 0


async def read_flags(
    driver: Any, group: str, limit: int = 100
) -> list[dict[str, Any]]:
    """Snapshot of flag state for one group (for the stats endpoint)."""
    rows, _, _ = await driver.execute_query(
        "MATCH ()-[r:RELATES_TO]->() WHERE r.group_id = $g "
        "RETURN r.fact_key AS key, r.version AS version, r.created_at AS created_at, "
        "r.deleted_at AS deleted_at, r.superseded_at AS superseded_at, "
        "r.superseded_by AS superseded_by, r.fact AS fact LIMIT $n",
        g=group,
        n=limit,
    )
    return [dict(r) for r in rows]
