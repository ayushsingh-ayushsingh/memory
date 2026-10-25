from __future__ import annotations

import time
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from .settings import Settings, get_settings


# %% Cell 05 — SERVICE PREFLIGHT: check dependencies *before* doing work
#
# The traceback you get from a stopped Qdrant container (`ConnectError:
# [Errno 111] Connection refused`) says nothing actionable. This cell turns
# that into a structured, readable report with a hint, and
# `require_services()` turns a failed check into one actionable exception
# instead of a stack of tracebacks deep inside a write path.


class ServiceUnavailable(RuntimeError):
    """Raised when a required service is not reachable."""

    def __init__(self, report: HealthReport, required: list[str]) -> None:
        self.report = report
        self.required = required
        lines = [f"required service(s) unavailable: {', '.join(required)}"]
        for svc in report.services:
            if svc.name in required:
                lines.append(f"  - {svc.name}: {svc.detail}")
                if svc.hint:
                    lines.append(f"    hint: {svc.hint}")
        super().__init__("\n".join(lines))


class ServiceStatus(BaseModel):
    """Outcome of a single dependency check."""

    model_config = ConfigDict(extra="forbid")

    name: str
    ok: bool
    detail: str = ""
    hint: str = ""
    latency_ms: float | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class HealthReport(BaseModel):
    """All dependency checks for one run."""

    model_config = ConfigDict(extra="forbid")

    services: list[ServiceStatus] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.services)

    def status(self, name: str) -> ServiceStatus | None:
        return next((s for s in self.services if s.name == name), None)

    def failed(self) -> list[str]:
        return [s.name for s in self.services if not s.ok]

    def rows(self) -> list[dict[str, Any]]:
        """Notebook-ready rows for the printed table."""
        return [
            {
                "service": s.name,
                "status": "OK" if s.ok else "FAIL",
                "detail": s.detail,
                "hint": s.hint,
                "latency_ms": s.latency_ms,
            }
            for s in self.services
        ]


def check_falkordb(settings: Settings | None = None) -> ServiceStatus:
    """Connect to FalkorDB, list graphs, report the configured stores."""
    st = settings or get_settings()
    start = time.perf_counter()
    try:
        from falkordb import FalkorDB

        db = FalkorDB(
            host=st.falkordb_host,
            port=st.falkordb_port,
            username=st.falkordb_user,
            password=st.falkordb_password,
        )
        graphs = list(db.list_graphs())
        elapsed = (time.perf_counter() - start) * 1000
        return ServiceStatus(
            name="falkordb",
            ok=True,
            detail=f"graphs: {', '.join(graphs) or '(none)'}",
            latency_ms=round(elapsed, 1),
            data={"graphs": graphs},
        )
    except Exception as exc:  # noqa: BLE001 — reported, never raised here
        elapsed = (time.perf_counter() - start) * 1000
        return ServiceStatus(
            name="falkordb",
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            hint=(
                f"start it: `docker start falkordb` (expect {st.falkordb_host}:"
                f"{st.falkordb_port})"
            ),
            latency_ms=round(elapsed, 1),
        )


def check_qdrant(settings: Settings | None = None) -> ServiceStatus:
    """Connect to Qdrant, report the fact collection + point count."""
    st = settings or get_settings()
    start = time.perf_counter()
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(
            url=st.qdrant_url,
            api_key=st.qdrant_api_key,
            timeout=st.qdrant_timeout_s,
        )
        names = [c.name for c in client.get_collections().collections]
        points = None
        if st.fact_collection in names:
            points = client.count(st.fact_collection, exact=True).count
        elapsed = (time.perf_counter() - start) * 1000
        detail = f"collections: {', '.join(names) or '(none)'}"
        if st.fact_collection in names:
            detail += f" | {st.fact_collection}: {points} points"
        else:
            detail += f" | {st.fact_collection}: missing (created on first write)"
        return ServiceStatus(
            name="qdrant",
            ok=True,
            detail=detail,
            latency_ms=round(elapsed, 1),
            data={"collections": names, "points": points},
        )
    except Exception as exc:  # noqa: BLE001 — reported, never raised here
        elapsed = (time.perf_counter() - start) * 1000
        return ServiceStatus(
            name="qdrant",
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            hint=f"start it: `docker start qdrant` (expect {st.qdrant_url})",
            latency_ms=round(elapsed, 1),
        )


def check_groq(settings: Settings | None = None) -> ServiceStatus:
    """Groq needs a key; the model itself is only contacted on demand."""
    st = settings or get_settings()
    if not st.groq_api_key:
        return ServiceStatus(
            name="groq",
            ok=False,
            detail="GROQ_API_KEY not set",
            hint="add GROQ_API_KEY to the project .env (extraction only)",
        )
    return ServiceStatus(
        name="groq",
        ok=True,
        detail=f"model {st.groq_model} (key present)",
        data={"model": st.groq_model},
    )


def check_jev(settings: Settings | None = None) -> ServiceStatus:
    """Jev needs a TypeSafe key; the model id and ceiling come from settings."""
    st = settings or get_settings()
    if not st.typesafe_api_key:
        return ServiceStatus(
            name="jev",
            ok=False,
            detail="TYPESAFE_API_KEY not set",
            hint="add TYPESAFE_API_KEY to the project .env (every ontology decision)",
        )
    return ServiceStatus(
        name="jev",
        ok=True,
        detail=(
            f"model {st.jev_model}, <= {st.jev_max_choices} choices/question, "
            f"{st.jev_max_questions_per_call} questions/request"
        ),
        data={"model": st.jev_model},
    )


def preflight(
    settings: Settings | None = None,
    checks: list[str] | None = None,
) -> HealthReport:
    """Run the requested checks (default: every service this notebook uses)."""
    st = settings or get_settings()
    wanted = checks or ["falkordb", "qdrant", "groq", "jev"]
    runners = {
        "falkordb": check_falkordb,
        "qdrant": check_qdrant,
        "groq": check_groq,
        "jev": check_jev,
    }
    return HealthReport(
        services=[runners[name](st) for name in wanted if name in runners]
    )


def require_services(
    report: HealthReport, required: list[str] | None = None
) -> HealthReport:
    """Raise `ServiceUnavailable` when a required service is down."""
    targets = required or [s.name for s in report.services]
    broken = [
        name
        for name in targets
        if (report.status(name) and not report.status(name).ok)
    ]
    if broken:
        raise ServiceUnavailable(report, broken)
    return report
