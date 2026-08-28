"""
/v1/languages — languages this model accepts.

OmniVoice supports several hundred languages and takes either an ID (`vi`) or
a full name (`vietnamese`). Neither list was discoverable through the API, and
an unrecognised value is not an error upstream: it falls back to
language-agnostic synthesis with only a server-side log line, so a typo comes
back as a subtly different voice and no explanation.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter()


@router.get("/languages")
async def list_languages(request: Request):
    """Language IDs and names accepted by the `language` parameter."""
    model_svc = request.app.state.model_svc
    if not model_svc.is_loaded:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model is still loading.",
        )

    languages = model_svc.supported_languages()
    return {
        "ids": languages["ids"],
        "names": languages["names"],
        "total": len(languages["ids"]),
        "note": (
            "The `language` parameter accepts either form, case-insensitively. "
            "Omit it for language-agnostic synthesis."
        ),
    }
