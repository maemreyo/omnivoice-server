"""
/v1/models — OpenAI-compatible model listing endpoint.

Some OpenAI SDK versions call GET /v1/models during client initialisation
to validate that the server is live and discover available models. Without
this endpoint those clients raise "model not found" or connection errors
before the first synthesis request.

This is a minimal, read-only stub — no inference happens here.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/audio/models")
@router.get("/models")
async def list_models(request: Request):
    """
    Returns the single model this server provides.
    Compatible with openai.models.list() and similar client checks.
    """
    cfg = request.app.state.cfg
    return {
        "object": "list",
        "data": [
            {
                "id": "omnivoice",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "k2-fsa",
                "permission": [],
                "root": cfg.model_id,
                "parent": None,
            },
            # Also advertise OpenAI alias names so drop-in clients that set
            # model="tts-1" don't get confused.
            {
                "id": "tts-1",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "k2-fsa",
                "permission": [],
                "root": cfg.model_id,
                "parent": "omnivoice",
            },
            {
                "id": "tts-1-hd",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "k2-fsa",
                "permission": [],
                "root": cfg.model_id,
                "parent": "omnivoice",
            },
        ],
    }


@router.get("/audio/models/{model_id}")
@router.get("/models/{model_id}")
async def get_model(model_id: str, request: Request):
    """Retrieve a specific model by ID."""
    cfg = request.app.state.cfg
    valid = {"omnivoice", "tts-1", "tts-1-hd"}
    if model_id not in valid:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_id}' not found. Available: {sorted(valid)}",
        )
    return {
        "id": model_id,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "k2-fsa",
        "root": cfg.model_id,
        "parent": None if model_id == "omnivoice" else "omnivoice",
    }
