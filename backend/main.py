import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError
from pydantic_ai import RunCancelled
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.ui import SSE_CONTENT_TYPE
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import TextUIPart, UIMessage

from src import store
from src.auth import get_current_user
from src.conductor import ChatDeps, conductor_agent
from src.conversations_api import router as conversations_router
from src.marimo_artifacts import router as artifacts_router
from src.memory import ingest_exchange, search_context
from src.toon_utils import natural_time

from dul_graph_rag.api import HOLDER as DUL_HOLDER
from dul_graph_rag.api import router as dul_router

_ = load_dotenv()

logger = logging.getLogger(__name__)

# How many prior turns (user + assistant pairs) to feed the coreference window
# when ingesting a new exchange. Groq's free plan is rate-limit sensitive, so we
# keep this small: enough context for pronouns to resolve, but few enough chunks
# to keep extraction calls low.
COREF_WINDOW_TURNS = 3

# Assistant identity used when prepending the reply for internal memory text.
ASSISTANT_NAME = "Joy AI"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create Postgres tables at startup; DUL session opens lazily on demand."""
    try:
        await store.init_db()
    except Exception:  # noqa: BLE001 — never block startup on a transient DB blip
        logger.exception("Postgres init failed at startup (will retry on first use)")
    yield
    # Close the shared DUL OntologySession (Jev + Graphiti) if it was opened.
    try:
        await DUL_HOLDER.close()
    except Exception:  # noqa: BLE001 — shutdown must never raise
        pass
    try:
        await store.close_db()
    except Exception:  # noqa: BLE001
        pass


app = FastAPI(lifespan=lifespan)

app.title = "Pydantic AI - Agent"

# Notebook export (POST) requires auth; generated files use unguessable ids.
app.include_router(artifacts_router)
# DUL graph-RAG (extract / search / CRUD). Auth is optional and controlled by
# DUL_REQUIRE_AUTH inside the router's own guard dependency.
app.include_router(dul_router)
# Conversations + account-data deletion (JWT-scoped to the current user).
app.include_router(conversations_router)

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
    # The chat response carries the minted conversation id in a custom header;
    # cross-origin JS may only read headers that are explicitly exposed.
    expose_headers=["X-Conversation-Id"],
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


# Strong references to in-flight background tasks (memory ingestion) so the
# event loop does not garbage-collect them before they finish.
_background_tasks: set[asyncio.Task[Any]] = set()


@app.get("/health")
async def health() -> dict[str, str]:
    """Public liveness probe. No authentication required."""
    return {"status": "ok"}


def _last_user_text(messages: list[UIMessage]) -> str:
    """Return the text of the newest user message in the client payload."""
    for msg in reversed(messages):
        if msg.role == "user":
            chunks = [
                part.text
                for part in msg.parts
                if isinstance(part, TextUIPart) and part.text
            ]
            text = "\n".join(chunks).strip()
            if text:
                return text
    return ""


def _extract_reply_text(result: Any) -> str:
    """Pull the assistant's plain-text reply out of an AgentRunResult."""
    output = getattr(result, "output", None)
    if isinstance(output, str) and output.strip():
        return output.strip()
    # Fall back to the last assistant response's text parts.
    try:
        for message in reversed(result.all_messages()):
            if isinstance(message, ModelResponse):
                parts = [
                    part.content
                    for part in message.parts
                    if isinstance(part, TextPart) and part.content
                ]
                text = "\n".join(parts).strip()
                if text:
                    return text
    except Exception:  # noqa: BLE001 — never fail the reply over extraction
        pass
    return ""


def _history_to_model_messages(
    prior: list[dict[str, Any]],
) -> list[ModelRequest | ModelResponse]:
    """Convert stored rows into trusted `message_history` for the agent run.

    This is server-owned history (from Postgres), so the browser never has to
    resend it — a conversation id plus the new prompt is enough.
    """
    history: list[ModelRequest | ModelResponse] = []
    for row in prior:
        content = (row.get("content") or "").strip()
        if not content:
            continue
        if row.get("role") == "user":
            history.append(
                ModelRequest(parts=[UserPromptPart(content=content)])
            )
        else:
            history.append(
                ModelResponse(parts=[TextPart(content=content)])
            )
    return history


def _build_final_input(
    prepended: str, context_toon: str
) -> str:
    """Assemble the agent's input: prepended prompt + optional TOON context."""
    if context_toon:
        return f"{prepended}\n\nExtracted context - {context_toon}"
    return prepended


def _coref_window_text(
    prior: list[dict[str, Any]],
    user_side: str,
    agent_side: str,
) -> str:
    """Text handed to coref + relation extraction after a turn.

    For a brand-new chat this is just the current exchange. For a longer chat we
    prepend the past `COREF_WINDOW_TURNS` user prompts and responses so pronouns
    resolve against recent context. The TOON "Extracted context" block is never
    included here — only the clean natural-language turns.
    """
    recent = prior[-(COREF_WINDOW_TURNS * 2) :] if prior else []
    window_parts: list[str] = []
    for row in recent:
        content = (row.get("content") or "").strip()
        if not content:
            continue
        if row.get("role") == "user":
            window_parts.append(content)
        else:
            window_parts.append(content)
    window = "\n".join(window_parts)
    current = f"{user_side}\n{agent_side}"
    if window:
        return f"{window}\n{current}"
    return current


def _replace_run_input_messages(
    run_input: Any, final_input: str, message_id: str
) -> None:
    """Swap the client's message list for a single server-built user message.

    The browser's full history is ignored: the agent sees only our preprocessed
    final input, with trusted prior turns supplied separately as `message_history`.
    """
    run_input.messages = [
        UIMessage(
            id=message_id,
            role="user",
            parts=[TextUIPart(text=final_input, state="done")],
        )
    ]


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

    user_id: str = str(user.get("sub", ""))
    user_name: str = str(user.get("name") or "the user").strip() or "the user"
    conversation_id: str = run_input.id

    prompt_text = _last_user_text(run_input.messages)
    if not user_id or not prompt_text:
        return Response(
            content=json.dumps(["No user prompt found in request"]),
            media_type="application/json",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    # Name a brand-new chat after its first message (the client no longer
    # renames; the backend owns the title from here on).
    auto_title = (
        prompt_text if len(prompt_text) <= 60 else f"{prompt_text[:60].rstrip()}…"
    )

    # Own the conversation in Postgres. Creating on demand keeps the client able
    # to send just an id (or 'new') without pre-provisioning a row.
    if conversation_id in ("", "new"):
        created = await store.create_conversation(user_id, title=auto_title)
        conversation_id = created["id"]
        run_input.id = conversation_id
        prior: list[dict[str, Any]] = []
    else:
        existing = await store.get_conversation(user_id, conversation_id)
        if existing is None:
            # Unknown or foreign id: mint a fresh conversation rather than leak.
            created = await store.create_conversation(user_id, title=auto_title)
            conversation_id = created["id"]
            run_input.id = conversation_id
            prior = []
        else:
            prior = await store.get_messages(user_id, conversation_id)

    now = datetime.now(timezone.utc)
    natural = natural_time(now)
    prepended = f"{user_name} said at {natural} - {prompt_text}"

    # Retrieve this user's memory for the prompt (limit 10), TOON-encoded with
    # natural dates. Empty string when nothing is stored.
    context_toon = await search_context(user_id, prepended, limit=10)
    final_input = _build_final_input(prepended, context_toon)

    _replace_run_input_messages(run_input, final_input, uuid.uuid4().hex)

    adapter = VercelAIAdapter(
        agent=conductor_agent, run_input=run_input, accept=accept, sdk_version=7
    )

    deps = ChatDeps(user_id=user_id, user_name=user_name)
    message_history = _history_to_model_messages(prior)

    # Captured by on_complete so we can persist the reply + kick off ingestion
    # without waiting for the client to close the stream.
    captured: dict[str, str] = {"reply": ""}

    async def _on_complete(result: Any) -> None:
        captured["reply"] = _extract_reply_text(result)
        try:
            await store.add_message(
                user_id, conversation_id, "user", prompt_text
            )
            if captured["reply"]:
                await store.add_message(
                    user_id, conversation_id, "assistant", captured["reply"]
                )
        except Exception:  # noqa: BLE001 — persistence must not break the stream
            logger.exception("failed to persist messages for %s", conversation_id)

        # Build memory text and ingest in the background so the user never waits.
        agent_side = (
            f"{ASSISTANT_NAME} replied at {natural_time(now)} - {captured['reply']}"
            if captured["reply"]
            else ""
        )
        memory_text = _coref_window_text(prior, prepended, agent_side)
        if memory_text.strip():
            task = asyncio.create_task(
                ingest_exchange(
                    user_id, memory_text, conversation_id=conversation_id
                )
            )
            # Keep a reference so the task is not garbage-collected mid-flight.
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    event_stream = adapter.run_stream(
        message_history=message_history,
        deps=deps,
        on_complete=_on_complete,
        on_cancel=on_cancel,
    )
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
            "X-Conversation-Id": conversation_id,
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
