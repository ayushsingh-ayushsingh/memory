# DUL Graph RAG

## What this is

This is a text-to-knowledge pipeline. It reads a long text. It turns the text
into facts. It stores the facts in two places:

- **FalkorDB** holds the facts as a knowledge graph.
- **Qdrant** holds the text and the facts as vectors.

You can then search both stores with one search call.

The system checks every fact against the **DOLCE** ontology before it stores
it. A fact that breaks the ontology is rejected. Nothing is stored un-checked.

## The short version

1. Send one long text to `POST /dul/extract`.
2. The system resolves pronouns, splits the text, and embeds it.
3. It extracts facts from each piece. Jev maps each fact to the ontology.
4. Only facts that pass the check are stored.
5. Search, update, or delete the facts through the other endpoints.

---

## How to run it

### 1. Start the services

You need three services running:

- **FalkorDB** on the port in `.env`.
- **Qdrant** on the port in `.env`.
- **Jev** (the ontology mapper). Its key is in `.env`.

### 2. Set the keys

Put these in `backend/.env`:

- `GROQ_API_KEY` — the key for the extraction model.
- `TYPESAFE_API_KEY` — the key for Jev.
- `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_USER`, `FALKORDB_PASSWORD`.
- `QDRANT_URL`.

Nothing in the code is hard-coded. Every host, port, model, and word list
comes from `.env`, `graph.json`, or `data/*.json`.

### 3. Start the app

```bash
cd backend
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

The DUL endpoints live under `/dul`.

---

## The endpoints

### `POST /dul/extract` — the main one

This is the most important endpoint. It does all the work in one call.

**What it takes:** one JSON body with one long text.

```json
{
  "text": "A long conversation or document...",
  "group": null,
  "doc_id": null,
  "embed_chunks": true
}
```

- `text` — the long text. Required.
- `group` — an optional name for a data slice. Uses the default if empty.
- `doc_id` — an optional ID. Give one to replace an earlier ingest.
- `embed_chunks` — set `false` to skip storing text vectors. Default is
  `true`.

**What it does:**

1. **Resolves pronouns.** "It" and "that" get replaced by what they mean.
   The result keeps the original word and adds the meaning in `<angle
   brackets>`. So "it <AI technology>" tells the extractor what "it" means.
2. **Splits the text.** The split makes pieces that do **not** overlap. Each
   piece is at most `DUL_CHUNK_SIZE` characters.
3. **Stores the pieces.** Each piece is embedded and saved in Qdrant.
4. **Extracts facts.** Each piece runs through the extractor at the same
   time. The extractor uses a large language model (LLM). The LLM only
   finds entities and relations. It does not pick ontology terms.
5. **Maps to the ontology.** Jev maps each entity and relation to a DOLCE
   term. Jev is not an LLM. It is a type-safe classifier.
6. **Checks the facts.** A strict gate checks each fact against the DOLCE
   rules. Only facts that pass are stored.
7. **Stores the facts.** Valid facts go into FalkorDB (as a graph) and
   Qdrant (as vectors).

**What it gives back:**

```json
{
  "doc_id": "doc-84e835727581",
  "group": "dul_jev",
  "text_chars": 2249,
  "resolved_chars": 2770,
  "chunks": 3,
  "chunk_op": "synced",
  "triples_created": 12,
  "triples_rejected": 2,
  "rejected_details": ["..."],
  "vector_status": "synced",
  "warnings": [],
  "chunk_outcomes": [],
  "usage": {},
  "elapsed_s": 26.9
}
```

- `chunks` — how many pieces the text became.
- `triples_created` — how many facts were stored.
- `triples_rejected` — how many facts failed the check.
- `rejected_details` — why each rejected fact failed.

---

### `POST /dul/search` — search everything

One search call searches both stores at the same time.

**What it takes:**

```json
{
  "query": "who works in the AI team",
  "limit": 10,
  "group": null,
  "include_deleted": false,
  "include_superseded": false,
  "include_chunks": true
}
```

- `query` — what you are looking for. Required.
- `limit` — the most results to return. Default is the setting value.
- `include_deleted` — set `true` to see deleted facts too.
- `include_superseded` — set `true` to see replaced facts too.
- `include_chunks` — set `false` to search only the facts, not the raw text.

**How it searches:**

1. **FalkorDB full text.** A keyword search over the fact graph.
2. **Qdrant fact vectors.** A meaning search over the fact vectors.
3. **Qdrant chunk vectors.** A meaning search over the raw text pieces.

All results are re-ranked by a local re-ranker. The system then applies two
weights:

- **Age weight.** Older facts count for less. The weight halves every
  `DUL_RECENCY_HALF_LIFE_DAYS` days (14 by default). Very old facts keep at
  least `DUL_RECENCY_FLOOR` of their weight (0.2 by default). Old facts lose
  weight. They never vanish.
- **Flag weight.** A fact that an update replaced counts for
  `DUL_SUPERSEDED_WEIGHT` (0.35 by default). A fact that a delete flagged
  counts for `DUL_DELETED_WEIGHT` (0 by default, so it is hidden).

**What it gives back:**

```json
{
  "query": "who works in the AI team",
  "hits": [
    {
      "fact": "Mohit works in team AI team.",
      "score": 1.19,
      "provenance": "qdrant-fact",
      "created_at": "2026-10-22 02:37:53.829847+00:00",
      "ref": "mohit|isConstituentOf|ai_team"
    }
  ],
  "legs": ["falkor", "qdrant-fact", "qdrant-chunk"],
  "notes": []
}
```

- `provenance` — which store the hit came from.
- `ref` — the fact ID (for facts) or the document ID (for text pieces).
- `legs` — which searches ran.
- `notes` — any search leg that failed. A failed leg does not stop the
  others.

---

### Facts: create, update, delete

These endpoints work with one fact at a time or many facts at once. A fact
is a triple: a subject, a relation, and an object. Each part carries a DOLCE
class or property.

#### Create one fact

`POST /dul/facts`

You can use short DOLCE names. The server fills in the long form for you.

```json
{
  "subject_name": "Mohit",
  "subject_class": "Agent",
  "relation": "hasLocation",
  "object_name": "Khargapur",
  "object_class": "Place",
  "fact_sentence": "Mohit is from Khargapur."
}
```

You can also send the long form if you prefer:

```json
{
  "subject_id": "mohit",
  "subject_name": "Mohit",
  "subject_class": "http://www.ontologydesignpatterns.org/ont/dul/DUL.owl#Agent",
  "relation": "http://www.ontologydesignpatterns.org/ont/dul/DUL.owl#hasLocation",
  "relation_name": "is from",
  "object_id": "khargapur",
  "object_name": "Khargapur",
  "object_class": "http://www.ontologydesignpatterns.org/ont/dul/DUL.owl#Place",
  "fact_sentence": "Mohit is from Khargapur.",
  "source": "api"
}
```

`subject_id` and `object_id` are optional. When you skip them, the server
makes an ID from the name. `subject_class`, `relation`, and `object_class`
can be a short name or a long DOLCE address. You can skip the two class
fields entirely: the server then picks a class that fits the relation's
declared domain and range. An unknown name is refused with HTTP 422 and the
reason.

No LLM runs here. No Jev runs here. The fact goes straight to the strict
gate. If it passes, it is stored. If not, you get the reasons.

#### Create many facts

`POST /dul/facts/bulk`

```json
{
  "triples": [ { ... }, { ... } ],
  "group": null
}
```

#### Update a fact

`PUT /dul/facts`

Use the same body as create.

**Updates do not delete anything.** The old fact stays in the graph. The
system flags it as `superseded` and points it at the new one. The new fact
gets a new version. Old facts lose search weight. They stay in the store.

#### Delete one fact

`DELETE /dul/facts/{fact_key}`

**Deletes do not remove anything.** The fact gets a `deleted_at` flag. It is
hidden from search by default. It is still in the graph. Set
`include_deleted: true` in search to see it.

#### Delete many facts or whole documents

`DELETE /dul/facts` (or `POST /dul/facts/bulk-delete`)

```json
{
  "fact_keys": ["mohit|hasLocation|khargapur"],
  "doc_ids": ["doc-84e835727581"],
  "group": null
}
```

Give `fact_keys` to delete facts by ID. Give `doc_ids` to delete everything
that came from one ingest run. You can give both. Use the `POST` alias when
your HTTP client cannot send a body on a `DELETE` request.

#### Delete one document

`DELETE /dul/docs`

```json
{ "doc_id": "doc-84e835727581", "group": null }
```

This retires one whole ingest run. It flags every fact and every text piece
that the run produced.

---

### `GET /dul/stats` — see what is stored

`GET /dul/stats`

```json
{
  "group": "dul_jev",
  "entities": 16,
  "edges": 19,
  "edges_live": 19,
  "edges_deleted": 0,
  "edges_superseded": 0,
  "docs": 0,
  "qdrant_points_total": 29,
  "qdrant_status": "up",
  "chunk_points_total": 0,
  "chunk_status": "missing",
  "sample": []
}
```

- `edges_live` — facts that are not deleted or replaced.
- `edges_deleted` — facts a delete flagged.
- `edges_superseded` — facts an update replaced.
- `docs` — how many ingest runs wrote facts.

### `GET /dul/health` — check the services

`GET /dul/health`

```json
{
  "status": "ok",
  "group": "dul_jev",
  "services": {
    "falkordb": true,
    "qdrant": true,
    "groq": true,
    "jev": true
  }
}
```

---

## The rules the system follows

### Nothing is ever deleted

A delete sets a flag. An update sets a flag. No fact is ever removed from
FalkorDB or Qdrant. The only way to clear data is a full reset. This is on
purpose. You can always look back at what the system knew and when.

### Old data counts for less

Search results are weighted by age. A fact that is 14 days old keeps half
its weight. A fact that is 28 days old keeps a quarter. Very old facts never
drop below 20% weight. So fresh facts rank first, but old facts can still be
found.

### The LLM has one job

The LLM (Groq `openai/gpt-oss-120b`) only finds entities and relations in
the text. It never picks an ontology term. That job belongs to Jev. This
keeps the LLM from inventing classes or properties.

### Jev does the mapping

Jev (TypeSafe) maps every entity to a DOLCE class and every relation to a
DOLCE property. Jev takes at most 10 choices per question. The pipeline
sends many questions in one call to keep the number of calls low. Jev runs
concurrently across text pieces.

### The gate never bends

A strict gate checks every fact against the DOLCE rules. It checks the
vocabulary, the class hierarchy, and the domain and range of each property.
A fact that fails is rejected and reported. There is no override.

---

## The settings

All settings come from `.env`. Each has a default.

| Setting | Default | What it does |
| --- | --- | --- |
| `DUL_CHUNK_SIZE` | 900 | The most characters in one text piece. |
| `DUL_COREF_ENABLED` | true | Turn pronoun resolution on or off. |
| `DUL_COREF_MAX_CHARS` | 40000 | The most characters sent to the pronoun model at once. |
| `DUL_COREF_DEVICE` | cpu | Where the pronoun model runs. |
| `DUL_EXTRACT_CONCURRENCY` | 4 | How many text pieces extract at once. |
| `DUL_RECENCY_HALF_LIFE_DAYS` | 14 | Days until a fact keeps half its weight. |
| `DUL_RECENCY_FLOOR` | 0.2 | The lowest weight an old fact can keep. |
| `DUL_SUPERSEDED_WEIGHT` | 0.35 | The weight of a fact an update replaced. |
| `DUL_DELETED_WEIGHT` | 0 | The weight of a fact a delete flagged. |
| `DUL_CHUNK_COLLECTION` | dul_chunks | The Qdrant collection for text pieces. |
| `DUL_REQUIRE_AUTH` | false | Set true to require a login token. |

### About auth

By default the DUL endpoints need no token. This makes them easy to test
with `curl`. For a shared or public server, set `DUL_REQUIRE_AUTH=true`.
Every endpoint then needs the same `Authorization: Bearer <token>` header
that the rest of the backend uses.

---

## How the pieces fit

```
backend/
  main.py                     the FastAPI app; mounts /dul
  dul_graph_rag/
    api.py                    the /dul endpoints
    modules/
      chunking.py             pronoun resolution + no-overlap split
      chunk_store.py          Qdrant store for text pieces
      longtext.py             the extract pipeline
      temporal.py             age weight + flag weight + flag helpers
      crud.py                 gated writes, hybrid search, soft delete
      vectors.py              Qdrant store for fact vectors
      mapping.py              Jev maps pairs; the gate validates
      extraction.py           the ONLY place an LLM runs
      gate.py                 the strict DOLCE check
      session.py              opens Jev + Graphiti once
      settings.py             every setting, from .env
  recursive_text_splitter.py  the no-overlap splitter
  ontology_enforced_triplet.py  the original single-file pipeline
```

### The layer rule

Each module only knows about the ones below it. `api.py` sits on top.
`settings.py` and `paths.py` sit at the bottom. This keeps changes small and
local.

---

## Common tasks

### Ingest a long document

```bash
curl -X POST http://localhost:8000/dul/extract \
  -H 'Content-Type: application/json' \
  -d '{"text": "Your long text here..."}'
```

### Search

```bash
curl -X POST http://localhost:8000/dul/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "who works in the AI team", "limit": 10}'
```

### See deleted facts too

```bash
curl -X POST http://localhost:8000/dul/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "who works in the AI team", "include_deleted": true}'
```

### Retire a whole ingest run

```bash
curl -X DELETE http://localhost:8000/dul/docs \
  -H 'Content-Type: application/json' \
  -d '{"doc_id": "doc-84e835727581"}'
```

### Check the counts

```bash
curl http://localhost:8000/dul/stats
```

---

## Troubleshooting

**`/dul/extract` takes a long time.**
The first call loads the pronoun model and the embedding models. Later calls
are faster. A very long text is split into many pieces. Each piece takes an
LLM call. Higher `DUL_EXTRACT_CONCURRENCY` runs more pieces at once.

**Facts are rejected.**
Read `rejected_details` in the extract response. It says why each fact
failed. Most rejections mean the class or property does not fit the DOLCE
rules for that relation.

**Search returns nothing.**
Check `/dul/health`. If a service is `false`, start it. Check `/dul/stats`.
If `edges_live` is `0`, no facts are stored yet.

**The chunk leg is missing from search.**
That means no text pieces are stored yet, or `embed_chunks` was `false`.
The other legs still work. This is not an error.

**Qdrant is down.**
Facts still go into FalkorDB. The Qdrant write is skipped and reported in
`warnings`. Run the sync tool later to backfill the vectors. The graph is
the source of truth.
