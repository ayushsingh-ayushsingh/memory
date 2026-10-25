import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError
from pydantic_ai import RunCancelled
from pydantic_ai.ui import SSE_CONTENT_TYPE
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from src.auth import get_current_user
from src.conductor import conductor_agent
from src.marimo_artifacts import router as artifacts_router

from dul_graph_rag.api import HOLDER as DUL_HOLDER
from dul_graph_rag.api import router as dul_router

_ = load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open nothing at startup (the DUL session opens lazily); close it on shutdown."""
    yield
    # Close the shared DUL OntologySession (Jev + Graphiti) if it was opened.
    try:
        await DUL_HOLDER.close()
    except Exception:  # noqa: BLE001 — shutdown must never raise
        pass


app = FastAPI(lifespan=lifespan)

app.title = "Pydantic AI - Agent"

# Notebook export (POST) requires auth; generated files use unguessable ids.
app.include_router(artifacts_router)
# DUL graph-RAG (extract / search / CRUD). Auth is optional and controlled by
# DUL_REQUIRE_AUTH inside the router's own guard dependency.
app.include_router(dul_router)

frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        frontend_url,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# A Groq rate-limit surfaces as a 429 ModelHTTPError whose message is a raw
# JSON blob (tokens-per-day / tokens-per-minute exhausted). The adapter already
# forwards it to the client as an `error` chunk, but the verbatim text is noise.
# Detect the rate-limit shape and swap in a short, actionable message so the UI
# shows "try again in a few minutes" instead of a Python traceback.
_RATE_LIMIT_MARKERS = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "429",
    "tokens per day",
    "tokens per minute",
    "retry-after",
    "try again in",
)

_RATE_LIMIT_MESSAGE = (
    "The AI model is temporarily rate-limited because its token budget is "
    "exhausted. Please wait a few minutes and try again."
)


def _friendly_error_text(text: str) -> str:
    lowered = text.lower()
    return _RATE_LIMIT_MESSAGE if any(m in lowered for m in _RATE_LIMIT_MARKERS) else text


async def _rewrite_rate_limit_errors(sse: AsyncIterator[str]) -> AsyncIterator[str]:
    """Post-process the SSE stream, replacing rate-limit `error` chunks."""
    async for line in sse:
        if line.startswith("data: "):
            payload = line[len("data: ") :].strip()
            try:
                obj = json.loads(payload)
            except (ValueError, TypeError):
                obj = None
            if isinstance(obj, dict) and obj.get("type") == "error":
                obj["errorText"] = _friendly_error_text(str(obj.get("errorText", "")))
                yield f"data: {json.dumps(obj)}\n\n"
                continue
        yield line


async def on_cancel(cancelled: RunCancelled) -> None:
    messages = cancelled.all_messages()
    print(f"cancelled after {len(messages)} messages")


@app.get("/health")
async def health() -> dict[str, str]:
    """Public liveness probe. No authentication required."""
    return {"status": "ok"}


@app.post("/chat")
async def chat(
    request: Request, user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> Response:
    accept = request.headers.get("accept", SSE_CONTENT_TYPE)
    try:
        run_input = VercelAIAdapter.build_run_input(await request.body())
    except ValidationError as e:
        return Response(
            content=json.dumps(e.json()),
            media_type="application/json",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    adapter = VercelAIAdapter(
        agent=conductor_agent, run_input=run_input, accept=accept, sdk_version=7
    )
    event_stream = adapter.run_stream(on_cancel=on_cancel)
    sse_event_stream = adapter.encode_stream(event_stream)
    # Explicit anti-buffering headers: without them, reverse proxies (and
    # some browsers) wait for the full body before rendering, which makes
    # first-token latency equal to full-response latency.
    return StreamingResponse(
        _rewrite_rate_limit_errors(sse_event_stream),
        media_type=accept,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
