# Marimo notebook artifacts — v1 (2026-09-17)

## Contract
- The conductor agent emits **one complete marimo notebook per answer** inside a
  single ```` ```python marimo ```` fence (never execute code server-side).
- Frontend parses fences from assistant message text → artifact panel.
- File upload/download for user tasks (e.g. image folder → zip) happens
  **inside the notebook** via `mo.ui.file` / `mo.download`. The Next.js chat UI
  has deliberately **no** file uploads.

## Backend (`chat_app/backend`, uv)
- `src/conductor.py`: `Agent(name="conductor", instructions=...,
  capabilities=[Skills(library, include=[10 marimo skills])])`.
  Skills lib resolves from repo-root `.agents/skills` (10 validated names in
  `MARIMO_SKILL_NAMES`; degrades to no-skills with a warning if missing).
  New deps: `pydantic-ai-harness[skills]`, `marimo`, `lzstring`.
- `src/marimo_artifacts.py` (router `/artifacts`, wired in `main.py`):
  - `POST /artifacts/export` (auth JWT) — validates marimo shape, stores
    `data/artifacts/<uuid-hex>/notebook.py`, runs
    `marimo export html-wasm --no-execute` (untrusted code NEVER runs
    server-side), rewrites asset refs to shared runtime, returns
    `{id, byte_size, exported, notebook_url, html_url, error}`.
    Limits: 500 KB source, 180 s timeout.
  - `GET /artifacts/{id}/notebook` + `GET /artifacts/{id}/html` — public,
    unguessable 128-bit ids (like sharing a molab link; needed because
    iframes cannot send `Authorization` headers).
  - `GET /artifacts/_runtime/{ver}/{path}` — shared ~28 MB Pyodide/editor
    runtime seeded once per marimo version; version-pinned, traversal-guarded.
  - Storage `backend/data/` is git-ignored.
- Verified: export → rewritten HTML (no `./assets/`) → JS 200, manifest 200,
  wrong-version/traversal 404, non-marimo 422.

## Frontend (`chat_app/client`, pnpm)
- `lib/marimo.ts`: `extractMarimoArtifacts` (handles streaming partials),
  `stripMarimoFences` (chat shows `> Notebook N is shown in the notebook
  panel.` / `> Generating notebook…`), `buildMolabEmbedUrl/OpenUrl`
  (lz-string, new dep `lz-string`), `SMALL_NOTEBOOK_BYTES = 14*1024`.
- `components/custom/marimo-artifact.tsx`: `MarimoArtifactPanel` (multi-notebook
  selector) + `MarimoArtifactView` (Preview/Code tabs; copy/download/fullscreen;
  NO open-in-molab link; large notebooks get server-render export flow with
  download fallback; lz-compression memoized, never during streaming).
  Fullscreen is the native Fullscreen API on the artifact container (true
  viewport fullscreen, Esc exits, auto-exits on unmount). Layout is full-bleed:
  no card/padding around the artifact — slim header bar, preview/code iframe
  fills the panel (`flex-1`, `min-h-[320px]` floor). Dark mode inverts preview
  iframes via `[data-mode="dark"] .marimo-frame { filter: invert(100%)
  hue-rotate(180deg); }` in `app/globals.css` (no `dark:` variant per guide;
  code views untouched — Shiki already dual-themed).
- `components/custom/chat-transcript.tsx`: assistant fences stripped for
  display (raw text kept for copy + DB persist → artifacts survive refresh);
  desktop `lg:` side panel (`w-[26rem]`); mobile Chat/Notebook tabs
  (derived state, auto-shows notebook on first artifact); per-agent fullscreen.
- `tsc --noEmit` + `eslint` pass. Kumo constraints hit: `Text` takes no
  `className`; `@phosphor-icons/react@2.1.10` has no `FlaskConicalIcon`
  (used `EyeIcon`); never conditionally render `Dialog`.

## Large-notebook strategy (>14 KB, URL embeds impractical)
1. Small: direct molab `#code/{lz-compressed}` iframe.
2. Large: backend `html-wasm` export (static, browser-executed) iframed.
3. Export fails / non-WASM notebook: code viewer + `.py` download + Open-in-molab.
4. Future: ephemeral Docker running `marimo run` per artifact (CPU/RAM/time
   limits, proxied session) for non-WASM-compatible notebooks — not built.

## v2 (2026-09-18): names, persistence, collapse, flash, floating input
- Titles: `extractMarimoArtifacts(id, text, startOrdinal)` numbers fallbacks
  globally (`Notebook 1..N` across the conversation); `deriveTitle` tries
  `mo.md("# T")` (inline/triple-quoted/f-string), then first top-level
  `# comment` outside PEP 723, then fallback. Conductor instructions require
  `mo.md("# <descriptive title>")` as the first cell. Identity for records:
  sync cyrb53 `hashNotebookCode` + global ordinal.
- Persistence: `notebook` table (user/conversation/codeHash/ordinal, nullable
  custom `title`, `autoTitle`, soft-delete `hidden`; cascade on conversation
  delete; `pnpm db:push` applied). Routes: `GET /api/notebooks` (visible +
  conversation title), `PATCH/DELETE /api/notebooks/[id]` (empty rename clears
  to derived; delete is soft), `GET/POST /api/conversations/[id]/notebooks`
  (sync upserts, never overwrites renames, refreshes autoTitle otherwise).
- Transcript syncs finished artifacts (signature-gated, never per-token);
  renames apply in past conversations, hidden ones are filtered. Sidebar
  `?notebook=<recordId>` deep-links (selects + opens panel, strips param).
- Sidebar: new `NotebookSidebar` group (search/rename/delete, navigates with
  deep link) + search box in `ChatSidebar`; store `lib/notebook-store.ts`.
- Panel collapses via header button (far right, `SidebarSimpleIcon`); slim
  reopen rail at the right edge. Mobile tabs follow collapse state.
- Iframes fade in on load (`ArtifactFrame`, keyed by src, themed placeholder
  behind) — no white flash. Composer is a floating overlay (capped 160px +
  internal scroll, `backdrop-blur-md shadow-lg`); transcript has `pb-48` so
  content never hides behind it; ScrollButton lifted to `bottom-44`.

## Next steps for future agents
- E2E test: prompt "make a marimo notebook that …" → panel appears right
  (desktop) / Notebook tab (mobile) → fullscreen works → >14 KB triggers
  Render preview.
- Optional: `POST /artifacts/export` Next.js proxy (same-origin iframe) if
  public-GET tradeoff needs revisiting; per-user artifact listing/GC for
  `data/artifacts`; `mo.ui.file` example prompts in conductor instructions.
