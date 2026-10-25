from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv
from groq import AsyncGroq
from pydantic_ai import Agent
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider

from .tools.search import (
    DEFAULT_LIMIT,
    SearchError,
    search_tool,
)

_ = load_dotenv()

logger = logging.getLogger(__name__)

# Agent Skills library (repo-root `.agents/skills`). Resolved from this file
# so the backend works regardless of the process working directory.
_SKILLS_LIBRARY = Path(__file__).resolve().parents[2] / ".agents" / "skills"

# Marimo-related skills the conductor may load on demand. The model initially
# sees only names + descriptions; bodies load via `load_capability`.
MARIMO_SKILL_NAMES = [
    "marimo-notebook",
    "wasm-compatibility",
    "anywidget-generator",
    "marimo-batch",
    "jupyter-to-marimo",
    "streamlit-to-marimo",
    "implement-paper",
    "implement-paper-auto",
    "auto-paper-demo",
    "add-molab-badge",
]

CONDUCTOR_INSTRUCTIONS = """\
You are the conductor assistant of a chat app. Every reply is rendered inline in
the conversation, and there are two ways to answer.

## Mode 1 — a generated interface (the default)

The app renders your reply with OpenUI (openui-lang): a list of component calls
that becomes live UI — Kumo cards, metrics, tables and animated charts. The
component library, its syntax, the hoisting rules and worked examples are the
"OpenUI — generated interface reference" appended at the end of these
instructions; follow it for every reply unless Mode 2 applies. Build the
smallest interface that answers the question: one `Text` for a short answer, a
row of `Metric` components for numbers, a `Table` for exact values, a `Chart`
only when the shape of the data is the point.

## Tool economy (important)

The model runs behind a tight token-rate limit, so keep tool use SMALL and
FEW. Prefer ONE broad `search` that covers the whole question over one search
per item — e.g. for "top 5 countries" search "population change 2023 India
China United States Indonesia Pakistan" once, not five separate country
searches. Aim for at most 2 tool calls total; never loop one call per row or
per entity. Answer from the first good result set instead of searching again.

## Mode 2 — a runnable marimo notebook

When the user asks for a Python program, a computation, data work, file
processing, a visualization, or an interactive tool that Python can solve, do
NOT answer with openui-lang: answer with a complete, valid marimo notebook
inside a single fenced block tagged `python marimo`. The app extracts it into
the notebook panel, where the user can run it.

```python marimo
# /// script
# requires-python = ">=3.12"
# dependencies = ["marimo"]
# ///

import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    mo.md("# Result")
    return


if __name__ == "__main__":
    app.run()
```

Notebook rules:
- The fence must contain a complete notebook: PEP 723 header, \
`import marimo`, `app = marimo.App(...)`, `@app.cell` functions, and the \
`if __name__ == "__main__": app.run()` footer.
- Use only real marimo APIs: render markdown with mo.md, tables with \
mo.ui.table/mo.ui.dataframe, Plotly figures with mo.ui.plotly, Altair charts \
with mo.ui.altair_chart, matplotlib figures by returning them (or mo.plt), \
media with mo.image/mo.audio/mo.video, files with mo.ui.file/mo.download. \
Never invent mo.* helpers (there is no mo.graph, mo.plot, mo.chart, \
mo.show, ...). When unsure how to display an object, just return it from \
the cell and let marimo render it.
- The first content cell must render a short descriptive title with \
`mo.md("# <Title>")` (e.g. `mo.md("# Image batch compressor")`). The chat \
UI uses this as the notebook's name, so never leave the default.
- Prefer WASM-compatible code (stdlib plus Pyodide-friendly packages; no \
subprocess, no os.system, no hardcoded local paths; declare every third-party \
dependency in the PEP 723 header).
- File upload/download happens INSIDE the notebook with mo.ui.file, \
mo.download, etc. The chat UI itself has no file uploads.
- Keep notebooks focused and small; after the fence, briefly explain what the \
notebook does and how to use it.
- A reply is either one interface or one notebook — never both, and never a \
marimo fence inside an openui-lang program.
"""

_capabilities: list = []
try:
    from pydantic_ai_harness import Skills

    if _SKILLS_LIBRARY.is_dir():
        _capabilities.append(
            Skills(str(_SKILLS_LIBRARY), include=MARIMO_SKILL_NAMES)
        )
    else:  # pragma: no cover - misconfigured checkout
        logger.warning("Skills library not found: %s", _SKILLS_LIBRARY)
except ImportError:  # pragma: no cover - harness not installed
    logger.warning("pydantic-ai-harness is not installed; skills disabled")

# ─────────────────────────────────────────────────────────────────────────────
# Generated-interface instructions (OpenUI)
# ─────────────────────────────────────────────────────────────────────────────
# The UI the model is allowed to build lives in the client
# (`client/lib/openui/library.tsx`). `pnpm openui:generate` (run in client/)
# turns those component definitions into the system prompt read below —
# component names, props, types, hoisting rules and examples all come from that
# one source of truth, so the model can only emit UI the renderer can draw.
#
# It is applied at import time: regenerate the file and restart the backend
# after changing the library. A missing file is not fatal — the conductor then
# answers in plain text instead of building interfaces.
_OPENUI_PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "client"
    / "lib"
    / "openui"
    / "generated"
    / "system-prompt.txt"
)


def _load_openui_prompt() -> str:
    """Read the generated OpenUI reference, or warn and degrade to markdown."""
    try:
        return _OPENUI_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        logger.warning(
            "OpenUI prompt not found at %s - run `pnpm openui:generate` in "
            "client/ to enable generated interfaces; answering in markdown.",
            _OPENUI_PROMPT_PATH,
        )
        return ""


OPENUI_INSTRUCTIONS = (
    "\n\n# OpenUI - generated interface reference\n"
    "# Generated from client/lib/openui/library.tsx by `pnpm openui:generate`;\n"
    "# do not edit by hand.\n\n" + _load_openui_prompt()
)

# Mode 1 (this reference) + Mode 2 (the marimo notebook rules above).
INSTRUCTIONS = CONDUCTOR_INSTRUCTIONS + OPENUI_INSTRUCTIONS


model = GroqModel(
    "openai/gpt-oss-120b",
    # The on-demand tier for gpt-oss-120b has a small token budget and its 429
    # backoff (`retry-after`) can stall a request for tens of seconds. With no
    # SDK-level retries a rate-limit error surfaces immediately instead, and the
    # /chat route turns it into a friendly "try again shortly" message rather
    # than leaving the user staring at a spinner.
    provider=GroqProvider(groq_client=AsyncGroq(max_retries=0)),
)
conductor_agent = Agent(
    model,
    name="conductor",
    instructions=INSTRUCTIONS,
    capabilities=_capabilities,
)


@conductor_agent.tool_plain
def search(query: str, number: int = DEFAULT_LIMIT) -> list[dict[str, str]] | str:
    """
    Get web-search results
    Args:
        query: str
        number: optional
    Retuns:
        [{url, title, content}]
    """
    try:
        return search_tool(query, number)
    except (SearchError, ValueError, TypeError) as exc:
        # Never fail the whole run when the search service is down:
        # let the model answer from its own knowledge instead.
        return f"Web search is temporarily unavailable ({exc}). Answer from your own knowledge and say so briefly."


app = conductor_agent.to_web()
