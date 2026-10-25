"""Filesystem anchors for the DUL ontology pipeline.

The original single-file notebook lived in ``backend/notebooks/`` but read its
artefacts (``.env``, ``graph.json``, ``data/*.json``) from the *backend root*.
It resolved them with ``Path(__file__).parent``, which pointed at
``backend/notebooks/`` and therefore silently missed ``backend/.env`` — the
settings fell back to their in-code defaults and every service check failed
confusingly.

This module walks *up* from its own location until it finds the project
marker (``pyproject.toml``), so the anchors stay correct however the package
is imported: from marimo, from pytest, from a plain ``python -c``, or from a
notebook that itself lives one level deeper.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

#: File that marks the project root. ``pyproject.toml`` is the most reliable
#: marker here: it sits next to ``.env``, ``graph.json`` and ``data/``.
PROJECT_MARKER = "pyproject.toml"


@lru_cache(maxsize=None)
def find_project_root(start: Path | str | None = None) -> Path:
    """Nearest ancestor of `start` (default: this file) holding the marker.

    Falls back to the current working directory rather than raising, so a
    missing marker produces one clear "file not found" at the call site
    instead of an import-time crash.
    """
    here = Path(start).resolve() if start is not None else Path(__file__).resolve()
    here = here if here.is_dir() else here.parent
    for candidate in (here, *here.parents):
        if (candidate / PROJECT_MARKER).is_file():
            return candidate
    return Path.cwd().resolve()


#: The ``backend/`` directory.
PROJECT_ROOT = find_project_root()

#: ``backend/.env`` — secrets and endpoints (never committed).
ENV_FILE = PROJECT_ROOT / ".env"

#: ``backend/data/`` — offline ontology snapshots.
DATA_DIR = PROJECT_ROOT / "data"

#: ``backend/graph.json`` — the DOLCE ontology export (source of truth).
ONTOLOGY_GRAPH_PATH = PROJECT_ROOT / "graph.json"

#: ``backend/data/artifacts/`` — generated marimo state (git-ignored).
ARTIFACTS_DIR = DATA_DIR / "artifacts"


def load_env(*, override: bool = False) -> Path | None:
    """Load ``backend/.env`` into the process environment. Idempotent.

    Returns the file that was loaded, or ``None`` when it is absent so a
    caller can report *why* the settings are running on defaults.
    """
    if not ENV_FILE.is_file():
        return None
    load_dotenv(ENV_FILE, override=override)
    return ENV_FILE


# Loading at import time is deliberate: `Settings` reads `ENV_FILE` the moment
# the class body is evaluated, so the .env has to be in place before
# `settings.py` is imported.
load_env()
