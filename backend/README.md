# Backend

FastAPI backend for the chat application.

## What it serves

- **`POST /chat`** — streaming chat through the conductor agent
  (`src/conductor.py`, pydantic-ai + Groq). The agent answers with an OpenUI
  generated interface or a runnable marimo notebook, and has a web-search tool.
- **`/artifacts`** — marimo notebook export/render endpoints
  (`src/marimo_artifacts.py`).
- **`/dul`** — DUL graph-RAG: ontology-enforced fact extraction, search, and
  time-based CRUD over FalkorDB (graph) + Qdrant (vectors)
  (`dul_graph_rag/`). See [dul_graph_rag/README.md](dul_graph_rag/README.md).
- **`GET /health`** — public liveness probe.

All other routes require a valid Better Auth JWT (`src/auth.py`), verified
statelessly via JWKS.

## Layout

```
main.py                 FastAPI app: routers, CORS, SSE chat route
src/
  auth.py               Better Auth JWT verification (JWKS)
  conductor.py          conductor agent (Groq + OpenUI + skills + search)
  marimo_artifacts.py   notebook export router (/artifacts)
  tools/search.py       web-search tool (Firecrawl)
dul_graph_rag/
  api.py                DUL router (/dul): extract / search / facts CRUD
  modules/              coref chunking, embeddings, graphiti, Jev, CRUD
```

## Prerequisites

- Docker (for Qdrant and FalkorDB) — compose file at the repo root.
- A Groq API key in `GROQ_API_KEY`.

## Setup

```bash
# 1. venv deps (uv sync picks up pyproject.toml)
cd backend
uv sync

# 2. start the datastores
docker compose up -d     # qdrant (localhost:6333) + falkordb (localhost:6379)

# 3. configure
cp .env.example .env     # then set GROQ_API_KEY (see .env.example)

# 4. run the API (from the repo root)
uv run uvicorn main:app --reload
```

## Environment variables

See [.env.example](.env.example). The variables in active use:

| Variable                  | Purpose                                          |
| ------------------------- | ------------------------------------------------ |
| `GROQ_API_KEY`            | *(required)* Groq API key                        |
| `QDRANT_URL`              | Qdrant endpoint (default `http://localhost:6333`)|
| `FALKORDB_HOST/PORT/...`  | FalkorDB connection (defaults in settings.py)    |
| `DUL_*`                   | DUL graph-RAG tuning (see `dul_graph_rag/modules/settings.py`) |
| `FRONTEND_URL`            | CORS origin for the Next.js client               |
| `BETTER_AUTH_*`           | JWT verification (JWKS URLs, issuer, audience)   |

## API

Interactive OpenAPI docs: `http://localhost:8000/docs`.

| Method | Path                          | Description                                    |
| ------ | ----------------------------- | ---------------------------------------------- |
| GET    | `/health`                     | Liveness probe (public).                       |
| POST   | `/chat`                       | Streaming chat (SSE, conductor agent).         |
| POST   | `/artifacts/export`           | Export a generated marimo notebook.            |
| POST   | `/dul/extract`                | Coref-resolve, chunk, embed, extract facts.    |
| POST   | `/dul/search`                 | Combined full-text + semantic + graph search.  |
| POST   | `/dul/facts`, `/dul/facts/bulk` | Create facts (single / bulk).                |
| PUT    | `/dul/facts`                  | Update facts (time-based superseding).         |
| DELETE | `/dul/facts`, `/dul/facts/bulk-delete` | Flag-delete facts (single / bulk).     |
| GET    | `/dul/stats`                  | Store statistics.                              |

## Notes

- The graph store is **FalkorDB** (via Graphiti); vectors live in **Qdrant**
  (FastEmbed local inference). No other graph database is used.
- DUL routes have their own optional auth guard (`DUL_REQUIRE_AUTH`), off by
  default for local curl testing.
