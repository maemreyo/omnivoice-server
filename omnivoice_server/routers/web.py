"""
Optional browser UI at /ui.

Motivation (issue #36): the first thing a new user wants is to hear the thing
work and to see what a real request looks like. Reading the README to build a
curl command is a poor substitute for either.

Served as a single self-contained HTML file rather than a mounted static
directory: there is exactly one asset, it has no build step, and a route keeps
it inside the same auth and CORS handling as everything else.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)
router = APIRouter()

INDEX_PATH = Path(__file__).resolve().parent.parent / "web" / "index.html"


def _read_index() -> str:
    return INDEX_PATH.read_text(encoding="utf-8")


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def web_ui() -> HTMLResponse:
    """The UI itself. Re-read per request so edits show up without a restart."""
    return HTMLResponse(_read_index())


@router.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    """
    Send the bare host to the UI.

    Only registered when the UI is enabled, so with `--no-web-ui` the root path
    keeps returning 404 exactly as it did before.
    """
    return RedirectResponse(url="/ui")


def index_exists() -> bool:
    """Whether the bundled UI asset is present (it may be stripped from a build)."""
    return INDEX_PATH.is_file()
