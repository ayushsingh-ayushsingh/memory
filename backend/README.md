# Backend

The backend is a Python service. It answers chat messages. It stores chats and it remembers what each user says. The Next.js client calls it on port 8000.

## What the backend does

- It streams chat answers with an AI agent called the conductor.
- It builds simple interfaces and marimo notebooks when a user asks for them.
- It searches the web when the agent needs facts.
- It stores chats and messages in PostgreSQL.
- It learns facts from chats and stores them in two memory stores: FalkorDB and Qdrant.
- It deletes a chat, or all data of a user, on request.

## Services and ports

| Service   | Port           | Purpose                                  |
| --------- | -------------- | ---------------------------------------- |
| Backend   | 8000           | This API                                 |
| PostgreSQL| 5432           | Chats and messages (system of record)    |
| pgAdmin   | 5050           | Web UI for PostgreSQL                    |
| FalkorDB  | 6379, 4001     | Memory graph and its browser UI          |
| Qdrant    | 6333           | Memory vectors                           |

Docker Compose at the repo root starts PostgreSQL, pgAdmin, FalkorDB, and Qdrant.

## How one chat turn works

1. The client sends one user message and a conversation id. For a new chat, the id is `new`.
2. The backend reads the user id and the user name from the auth token.
3. It adds the user name and the current time to the message. Example: `Neo said at October 25, 2026 at 1:01:13 PM - What is my favorite color?`
4. It searches the memory stores with this text. It uses at most 10 results.
5. It converts the results to TOON format. It converts each date to natural format first.
6. It gives the text plus the TOON results to the conductor agent.
7. The agent answers in natural language. It can also call tools to read or change memory.
8. The backend saves the user message and the answer in PostgreSQL.
9. A background task learns from the exchange. It resolves references, extracts facts, and stores embeddings.

## Rules that the backend follows

- A new chat gets an id at step 8, before the model runs. The backend returns this id in the `X-Conversation-Id` header. The client shows the id in the address bar after the turn.
- The backend sets the chat title from the first user message.
- The agent instructions include the current user name from the auth token. The agent always uses this name, even when older facts show a different name.
- Every fact and every embedding carries a group key: `user:<id>`. All searches and deletions filter by this key. One user cannot read or change data of another user.
- A Groq rate-limit error becomes a short message. The user sees "wait a few minutes and try again".
- The client sends only the conversation id and the new message. It never sends the chat history.

## Deleting data

- Delete one chat: the user chooses to delete only the chat, or the chat and also the learned facts.
- Delete all data: `POST /account/delete-data` deletes all chats and all learned facts of the user. It does not delete the account.
- The dialogs use plain English. They do not name the technical stores.

## Layout

```
main.py                 FastAPI app: CORS, SSE chat route, conversation routes
src/
  auth.py               Better Auth JWT verification (JWKS)
  conductor.py          conductor agent (Groq, OpenUI, skills, search, CRUD tools)
  conversations_api.py  chat list, chat detail, delete chat, delete all data
  memory.py             memory search, fact ingest, fact CRUD, wipe helpers
  store.py              PostgreSQL chats and messages (SQLAlchemy)
  toon_utils.py         JSON to TOON, dates to natural format
  marimo_artifacts.py   notebook export router (/artifacts)
  tools/search.py       web-search tool (Firecrawl)
dul_graph_rag/
  api.py                DUL router (/dul): extract, search, facts CRUD
  modules/              coref chunking, embeddings, graphiti, Jev, CRUD
```

See [dul_graph_rag/README.md](dul_graph_rag/README.md) for the memory engine.

## Prerequisites

- Docker, with the compose file at the repo root.
- A Groq API key in `GROQ_API_KEY`.
- The Next.js client on port 3000. It mints the auth tokens.

## Setup

1. Install the Python dependencies:

   ```bash
   cd backend
   uv sync
   ```

2. Start the services:

   ```bash
   docker compose up -d
   ```

3. Configure the environment:

   ```bash
   cp .env.example .env
   ```

   Set `GROQ_API_KEY` in `.env`.

4. Start the API from the `backend` directory:

   ```bash
   uv run uvicorn main:app --reload
   ```

5. Check the service:

   ```bash
   curl http://localhost:8000/health
   ```

## Environment variables

See [.env.example](.env.example). The variables in active use:

| Variable                 | Purpose                                          |
| ------------------------ | ------------------------------------------------ |
| `GROQ_API_KEY`           | Required. Groq API key.                          |
| `QDRANT_URL`             | Qdrant endpoint. Default `http://localhost:6333`.|
| `FALKORDB_HOST`, `FALKORDB_PORT` | FalkorDB connection. Defaults in `settings.py`. |
| `POSTGRES_URL`           | PostgreSQL connection string.                    |
| `DUL_*`                  | Memory engine tuning. See `dul_graph_rag/modules/settings.py`. |
| `FRONTEND_URL`           | CORS origin for the client.                      |
| `BETTER_AUTH_*`          | JWT verification: JWKS URLs, issuer, audience.   |

## API

Interactive docs: `http://localhost:8000/docs`.

All routes except `/health` need a valid Better Auth JWT.

| Method | Path                                | Description                                    |
| ------ | ----------------------------------- | ---------------------------------------------- |
| GET    | `/health`                           | Liveness probe. Public.                        |
| POST   | `/chat`                             | Streaming chat (SSE). Returns the conversation id in `X-Conversation-Id`. |
| GET    | `/conversations`                    | List the chats of the user.                    |
| GET    | `/conversations/{id}`               | One chat with its messages.                    |
| DELETE | `/conversations/{id}`               | Delete a chat. With `forget_memory=true`, also delete its learned facts. |
| POST   | `/account/delete-data`              | Delete all chats and all learned facts. Keeps the account. |
| GET    | `/dul/stats`                        | Memory statistics for one user.                |
| POST   | `/dul/search`                       | Full-text, semantic, and graph search.         |
| POST   | `/dul/extract`                      | Resolve references, chunk, embed, extract facts. |
| POST   | `/dul/facts`, `/dul/facts/bulk`     | Create facts. Single or bulk.                  |
| PUT    | `/dul/facts`                        | Update facts. Old versions stay for history.   |
| DELETE | `/dul/facts`, `/dul/facts/bulk-delete` | Flag-delete facts. Single or bulk.          |
| POST   | `/artifacts/export`                 | Export a generated marimo notebook.            |

## Notes

- The memory engine is DOLCE Ultra-lite (DUL) graph-RAG. FalkorDB holds the fact graph. Qdrant holds the vectors. FastEmbed runs the embeddings locally.
- PostgreSQL stores chats and messages only. The memory stores hold the learned facts. The same text is not saved twice.
- The conductor agent has tools for memory CRUD and bulk CRUD. The tools take ids for soft update and soft delete.
