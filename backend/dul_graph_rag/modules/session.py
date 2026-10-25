"""Session lifecycle: preflight -> ontology self-check -> Jev + Graphiti.

This is the code that used to be scattered across the notebook's "EXECUTION"
cells (20-22 and the teardown cell). It is deliberately small and explicit:
nothing below performs a mapping or a write, it only decides whether the
process is allowed to do so and then opens the two long-lived connections.

Use it as an async context manager::

    async with OntologySession() as session:
        report = await session.ingest("some text")
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .clients import close_graphiti, get_graphiti
from .deps import get_jev_deps
from .jev import JevClient
from .ontology import self_check
from .preflight import HealthReport, preflight, require_services
from .settings import S, Settings, get_settings
from .stores import GraphStore, stores


class OntologySelfCheckError(RuntimeError):
    """The DOLCE export does not carry the verified counts any more.

    The counts (478 records; 77 classes / 112 object properties / 5 data
    properties / 1 other) are the contract the strict gate is written against.
    If a replacement `graph.json` changes them, mapping would silently target
    half of DUL, so this fails loudly instead.
    """

    def __init__(self, mismatches: list[str]) -> None:
        self.mismatches = mismatches
        super().__init__(
            "ontology self-check failed -- the export no longer matches the "
            "verified counts:\n  - " + "\n  - ".join(mismatches)
        )


#: Services without which nothing downstream can work. Groq and Qdrant are
#: checked but not required: Groq is only needed for the extraction stage and
#: the Qdrant mirror is best-effort by design.
REQUIRED_SERVICES = ("falkordb", "jev")


@dataclass(slots=True)
class OntologySession:
    """Everything a run needs, opened once and closed once.

    Attributes are populated by `open()`; accessing them beforehand raises so
    a half-opened session cannot be used by accident.
    """

    settings: Settings | None = None
    health: HealthReport | None = None
    checks: dict[str, Any] = field(default_factory=dict)
    jev: JevClient | None = None
    graphiti: Any = None
    deps: dict[str, Any] = field(default_factory=dict)
    graph_stores: list[GraphStore] = field(default_factory=list)
    _owns_loop: bool = False
    _opened: bool = False

    # %% property access -------------------------------------------------
    @property
    def group(self) -> str:
        """The logical partition every read/write is scoped to."""
        if self.settings is None:
            raise RuntimeError("session is not open")
        return self.settings.jev_group

    @property
    def s(self) -> Settings:
        if self.settings is None:
            raise RuntimeError("session is not open")
        return self.settings

    # %% lifecycle -------------------------------------------------------
    async def open(self, *, require: tuple[str, ...] = REQUIRED_SERVICES) -> OntologySession:
        """Run the preflight, the self-check, then open Jev and Graphiti."""
        s = self.settings or get_settings()
        self.settings = s

        self.health = await asyncio.to_thread(preflight, s)
        require_services(self.health, required=list(require))

        result = self_check()
        if not result["ok"]:
            raise OntologySelfCheckError(list(result["mismatches"]))
        self.checks = result

        # NOTE: `get_jev_deps()`, `stores()` and `get_graphiti()` take no
        # arguments on purpose -- they read the process-wide settings singleton
        # (`.settings.S`), so the same snapshot is used by every module.
        self.deps = get_jev_deps()
        self.graph_stores = stores()

        self.jev = JevClient(s)
        await self.jev.__aenter__()
        try:
            self.graphiti = await get_graphiti()
        except BaseException:
            await self.jev.__aexit__(None, None, None)
            self.jev = None
            raise

        self._opened = True
        return self

    async def close(self) -> None:
        """Close Jev and Graphiti. Safe to call twice."""
        if self.jev is not None:
            await self.jev.__aexit__(None, None, None)
            self.jev = None
        if self.graphiti is not None:
            await close_graphiti()
            self.graphiti = None
        self._opened = False

    async def __aenter__(self) -> OntologySession:
        return await self.open()

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # %% convenience ------------------------------------------------------
    def require_open(self) -> None:
        if not self._opened:
            raise RuntimeError("session is not open -- use `async with OntologySession()`")

    async def ingest(self, text: str, *, group: str | None = None) -> Any:
        """Map `text` onto DUL triples and write the ones that pass the gate."""
        from .pipeline import ingest  # local import: pipeline depends on this module

        self.require_open()
        return await ingest(text, session=self, group=group)

    async def stats(self, group: str | None = None) -> dict[str, Any]:
        from .facade import stats as _stats

        self.require_open()
        return await _stats(self.graphiti, group=group or self.group)

    async def search(self, query: str, *, limit: int | None = None, group: str | None = None) -> Any:
        from .facade import search as _search

        self.require_open()
        return await _search(
            self.graphiti, self.deps, query, limit=limit, group=group or self.group
        )


# %% One-lifecycle helpers for scripts that do not want a context manager


def _run(coro: Any) -> Any:
    """Run `coro` to completion, whether or not a loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop in this thread: plain `asyncio.run` is the simplest thing
        # that works.
        return asyncio.run(coro)
    # A loop is already running (e.g. marimo keeps one alive across cells), so
    # we cannot block it. Run on a dedicated thread with its own loop.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def open_session(**kwargs: Any) -> OntologySession:
    """Synchronously open a session (for a plain script or a notebook cell)."""
    session = OntologySession(**kwargs)
    return _run(session.open())


def close_session(session: OntologySession) -> None:
    """Synchronously close a session opened by `open_session()`."""
    _run(session.close())


__all__ = [
    "REQUIRED_SERVICES",
    "OntologySelfCheckError",
    "OntologySession",
    "close_session",
    "open_session",
    "preflight",
    "require_services",
    "self_check",
    "stores",
    "S",
]
