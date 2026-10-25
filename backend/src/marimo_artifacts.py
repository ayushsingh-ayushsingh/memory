"""Server-side fallback for marimo notebooks too large for URL embeds.

Small notebooks (< 14 KB) are embedded directly in the client via an
lz-string-compressed molab URL
(`https://molab.marimo.io/new/wasm/?embed=true#code/{compressed}`).
That breaks down for large notebooks: the compressed payload still grows
with the source and eventually exceeds practical URL/iframe limits.

This router implements the v1 fallback:

- ``POST /artifacts/export`` (auth) stores the notebook source and runs
  ``marimo export html-wasm`` **without** ``--execute`` (untrusted code is
  never run server-side). The export is a static WASM page that executes in
  the visitor's browser via Pyodide.
- ``GET /artifacts/{id}/html`` serves the exported page; ``GET
  /artifacts/{id}/notebook`` serves the ``.py`` source for download.
- The ~28 MB Pyodide/editor runtime (``assets/``) is identical for every
  export from the same marimo version, so it is seeded once under
  ``_runtime/{version}/`` and shared. Served HTML is rewritten to reference
  it via absolute paths.

``GET`` routes are intentionally public: ids are unguessable 128-bit hex
(random, not content-derived), exactly like sharing a molab link. ``POST``
requires a valid Better Auth JWT.

Future (serverless Docker): run ``marimo run`` per artifact in an ephemeral
container with CPU/RAM/time limits and proxy the session for notebooks that
are not WASM-compatible (native deps, sockets, long-running kernels).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Any

import marimo
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

MARIMO_VERSION = marimo.__version__

# Storage layout (all under backend/data/artifacts, git-ignored):
#   <id>/notebook.py   raw source (download)
#   <id>/notebook.html exported WASM page with asset refs rewritten
#   _runtime/<ver>/... shared Pyodide/editor runtime + icons
STORE_DIR = Path(__file__).resolve().parents[1] / "data" / "artifacts"
RUNTIME_DIR = STORE_DIR / "_runtime" / MARIMO_VERSION

MAX_SOURCE_BYTES = 512_000  # 500 KB of source; beyond this, refuse loudly
EXPORT_TIMEOUT_SECONDS = 180

_HTML_ASSET_PREFIX = '"./assets/'
_HTML_ASSET_PREFIX_SINGLE = "'./assets/"
_STATIC_FILES = (
    "apple-touch-icon.png",
    "favicon-16x16.png",
    "favicon-32x32.png",
    "favicon.ico",
    "logo.png",
    "manifest.json",
    "site.webmanifest",
    "android-chrome-192x192.png",
    "android-chrome-512x512.png",
)


class ExportRequest(BaseModel):
    code: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES)
    filename: str = Field(default="notebook.py", max_length=120)


class ExportResponse(BaseModel):
    id: str
    byte_size: int
    exported: bool
    notebook_url: str
    html_url: str | None = None
    error: str | None = None


def _is_marimo_notebook(code: str) -> bool:
    return "marimo" in code and ("marimo.App" in code or "@app.cell" in code)


def _rewrite_asset_refs(html: str) -> str:
    """Point the exported page at the shared runtime directory.

    Only known static prefixes are rewritten so notebook-embedded strings
    (e.g. ``open("./data.csv")`` in user code) are left untouched.
    """
    base = f"/artifacts/_runtime/{MARIMO_VERSION}"
    html = html.replace(_HTML_ASSET_PREFIX, f'"{base}/assets/')
    html = html.replace(_HTML_ASSET_PREFIX_SINGLE, f"'{base}/assets/")
    for name in _STATIC_FILES:
        html = html.replace(f'"./{name}"', f'"{base}/{name}"')
        html = html.replace(f"'./{name}'", f"'{base}/{name}'")
    return html


async def _export_html_wasm(source: Path, out_html: Path) -> None:
    """Run `marimo export html-wasm` WITHOUT --execute (never runs code)."""
    cmd = [
        sys.executable,
        "-m",
        "marimo",
        "export",
        "html-wasm",
        str(source),
        "-o",
        str(out_html),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(
            proc.communicate(), timeout=EXPORT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError(
            f"export timed out after {EXPORT_TIMEOUT_SECONDS}s"
        ) from None
    if proc.returncode != 0 or not out_html.exists():
        detail = (stdout or b"").decode(errors="replace")[-2000:]
        raise RuntimeError(f"marimo export failed: {detail}")


def _seed_shared_runtime(tmp_dir: Path) -> None:
    """Move the first export's runtime assets into the shared directory."""
    if RUNTIME_DIR.exists():
        return
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    for child in tmp_dir.iterdir():
        if child.name in ("notebook.py", "notebook.html"):
            continue
        target = RUNTIME_DIR / child.name
        if target.exists():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
            continue
        shutil.move(str(child), str(target))


@router.post("/export", response_model=ExportResponse)
async def export_notebook(
    body: ExportRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> ExportResponse:
    code = body.code
    byte_size = len(code.encode("utf-8"))
    if byte_size > MAX_SOURCE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Notebook source exceeds {MAX_SOURCE_BYTES} bytes",
        )
    if not _is_marimo_notebook(code):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request body does not look like a marimo notebook",
        )

    artifact_id = uuid.uuid4().hex
    artifact_dir = STORE_DIR / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "notebook.py").write_text(code, encoding="utf-8")

    notebook_url = f"/artifacts/{artifact_id}/notebook"
    try:
        with tempfile.TemporaryDirectory(prefix="marimo-export-") as tmp:
            tmp_dir = Path(tmp)
            src = tmp_dir / "notebook.py"
            out = tmp_dir / "notebook.html"
            src.write_text(code, encoding="utf-8")
            await _export_html_wasm(src, out)
            _seed_shared_runtime(tmp_dir)
            html = out.read_text(encoding="utf-8")
        (artifact_dir / "notebook.html").write_text(
            _rewrite_asset_refs(html), encoding="utf-8"
        )
    except Exception as exc:  # export failed: source stays downloadable
        logger.warning("marimo export failed for %s: %s", artifact_id, exc)
        return ExportResponse(
            id=artifact_id,
            byte_size=byte_size,
            exported=False,
            notebook_url=notebook_url,
            html_url=None,
            error=str(exc)[:500],
        )

    # Best-effort integrity check (helps catch truncated writes).
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:12]
    logger.info(
        "exported artifact %s (%d bytes, sha %s) for sub=%s",
        artifact_id,
        byte_size,
        digest,
        user.get("sub"),
    )
    return ExportResponse(
        id=artifact_id,
        byte_size=byte_size,
        exported=True,
        notebook_url=notebook_url,
        html_url=f"/artifacts/{artifact_id}/html",
    )


def _artifact_file(artifact_id: str, name: str) -> Path:
    if len(artifact_id) != 32 or any(
        c not in "0123456789abcdef" for c in artifact_id
    ):
        raise HTTPException(status_code=404, detail="Artifact not found")
    path = STORE_DIR / artifact_id / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return path


@router.get("/{artifact_id}/notebook")
async def download_notebook(artifact_id: str) -> FileResponse:
    path = _artifact_file(artifact_id, "notebook.py")
    return FileResponse(
        path, media_type="text/x-python", filename="notebook.py"
    )


@router.get("/{artifact_id}/html")
async def view_exported_notebook(artifact_id: str) -> HTMLResponse:
    path = _artifact_file(artifact_id, "notebook.html")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.get("/_runtime/{marimo_version}/{file_path:path}")
async def serve_runtime_file(
    marimo_version: str, file_path: str
) -> FileResponse:
    # Pin to the running marimo version; block traversal explicitly.
    if marimo_version != MARIMO_VERSION or ".." in file_path:
        raise HTTPException(status_code=404, detail="Not found")
    path = RUNTIME_DIR / file_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    if path.suffix == ".js":
        return FileResponse(path, media_type="text/javascript")
    if path.suffix == ".css":
        return FileResponse(path, media_type="text/css")
    if path.suffix == ".json":
        return FileResponse(path, media_type="application/json")
    if path.suffix == ".wasm":
        return FileResponse(path, media_type="application/wasm")
    return FileResponse(path)


@router.get("/health")
async def artifacts_health() -> PlainTextResponse:
    return PlainTextResponse(f"ok marimo={MARIMO_VERSION}")
