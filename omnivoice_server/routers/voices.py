"""
/v1/voices                    — list all available voices
/v1/voices/profiles           — manage cloning profiles
/v1/voices/profiles/{id}      — get/patch/delete specific profile
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from ..services.model import ModelService
from ..services.profiles import (
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
    ProfileService,
)
from ..voice_presets import DEFAULT_DESIGN_INSTRUCTIONS, DESIGN_ATTRIBUTES, OPENAI_VOICE_PRESETS

logger = logging.getLogger(__name__)
router = APIRouter()
compat_router = APIRouter()


class VoiceUpdate(BaseModel):
    """Metadata fields used by the faster-qwen3-tts voice API."""

    name: str | None = Field(default=None, max_length=128)
    ref_text: str | None = Field(default=None, max_length=10_000)


def _get_profiles(request: Request) -> ProfileService:
    return request.app.state.profile_svc


def _get_model(request: Request) -> ModelService:
    return request.app.state.model_svc


# ── GET /v1/voices ───────────────────────────────────────────────────────────


@router.get("/voices")
async def list_voices(
    profile_svc: ProfileService = Depends(_get_profiles),
):
    built_in = [
        {
            "id": "auto",
            "type": "auto",
            "description": (
                "Fallback/default prompt when no instructions or recognized preset is provided: "
                f"{DEFAULT_DESIGN_INSTRUCTIONS}"
            ),
        },
        {
            "id": "design:<attributes>",
            "type": "design",
            "description": "Voice design via attributes. Example: 'design:female,british accent'",
        },
    ] + [
        {
            "id": preset_name,
            "type": "preset",
            "description": f"OpenAI-compatible preset mapped to '{prompt}'",
        }
        for preset_name, prompt in sorted(OPENAI_VOICE_PRESETS.items())
    ]

    profiles = profile_svc.list_profiles()
    clone_voices = [
        {
            "id": f"clone:{p['profile_id']}",
            "type": "clone",
            "profile_id": p["profile_id"],
            "created_at": p.get("created_at"),
            "ref_text": p.get("ref_text"),
        }
        for p in profiles
    ]

    return {
        "voices": built_in + clone_voices,
        "design_attributes": DESIGN_ATTRIBUTES,
        "total": len(built_in) + len(clone_voices),
    }


# ── POST /v1/voices/profiles ─────────────────────────────────────────────────


@router.post("/voices/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(
    request: Request,  # FIX: was missing — needed for cfg access
    profile_id: str = Form(
        ...,
        pattern=r"^[a-zA-Z0-9_-]{1,64}$",
        description="Unique identifier. Alphanumeric, dashes, underscores only.",
    ),
    ref_audio: UploadFile = File(...),
    ref_text: str | None = Form(default=None),
    overwrite: bool = Form(default=False),
    profile_svc: ProfileService = Depends(_get_profiles),
    model_svc: ModelService = Depends(_get_model),
):
    """
    Save a voice cloning profile.
    Use /v1/audio/speech/clone for synthesis with reference audio uploads.
    """
    from ..utils.audio import read_upload_bounded, validate_audio_bytes

    cfg = request.app.state.cfg  # FIX: was NameError previously

    raw = await ref_audio.read(cfg.max_ref_audio_bytes + 1)
    try:
        audio_bytes = read_upload_bounded(raw, cfg.max_ref_audio_bytes)
        validate_audio_bytes(audio_bytes)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )

    try:
        meta = profile_svc.save_profile(
            profile_id=profile_id,
            audio_bytes=audio_bytes,
            ref_text=ref_text,
            overwrite=overwrite,
        )
    except ProfileAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    model_svc.invalidate_voice_clone_prompt(profile_id)
    return meta


# ── GET /v1/voices/profiles/{profile_id} ─────────────────────────────────────


@router.get("/voices/profiles/{profile_id}")
async def get_profile(
    profile_id: str,
    profile_svc: ProfileService = Depends(_get_profiles),
):
    profiles = profile_svc.list_profiles()
    profile = next((p for p in profiles if p["profile_id"] == profile_id), None)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found",
        )
    return profile


# ── DELETE /v1/voices/profiles/{profile_id} ──────────────────────────────────


@router.delete("/voices/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    request: Request,
    profile_id: str,
    profile_svc: ProfileService = Depends(_get_profiles),
):
    try:
        profile_svc.delete_profile(profile_id)
    except (ProfileNotFoundError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found",
        )

    request.app.state.model_svc.invalidate_voice_clone_prompt(profile_id)


# ── PATCH /v1/voices/profiles/{profile_id} ───────────────────────────────────


@router.patch("/voices/profiles/{profile_id}", status_code=status.HTTP_200_OK)
async def update_profile(
    profile_id: str,
    request: Request,  # FIX: needed for cfg.max_ref_audio_bytes
    ref_audio: UploadFile | None = File(default=None),
    ref_text: str | None = Form(default=None),
    profile_svc: ProfileService = Depends(_get_profiles),
    model_svc: ModelService = Depends(_get_model),
):
    """
    Update an existing profile. Fields not provided are left unchanged.
    """
    # Verify it exists first
    try:
        profile_svc.get_ref_audio_path(profile_id)
    except (ProfileNotFoundError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found",
        )

    if ref_audio is None and ref_text is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide at least one of: ref_audio, ref_text",
        )

    if ref_audio is not None:
        from ..utils.audio import read_upload_bounded, validate_audio_bytes

        cfg = request.app.state.cfg
        raw = await ref_audio.read(cfg.max_ref_audio_bytes + 1)
        try:
            # FIX: PATCH was missing size + format validation entirely
            audio_bytes = read_upload_bounded(raw, cfg.max_ref_audio_bytes)
            validate_audio_bytes(audio_bytes)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(e),
            )
        meta = profile_svc.update_profile(
            profile_id,
            audio_bytes=audio_bytes,
            ref_text=ref_text,
            update_ref_text=ref_text is not None,
        )
    else:
        meta = profile_svc.update_profile(
            profile_id,
            ref_text=ref_text,
            update_ref_text=True,
        )

    model_svc.invalidate_voice_clone_prompt(profile_id)
    return meta


def _audio_voice_item(profile: dict) -> dict:
    profile_id = profile["profile_id"]
    created = 0
    created_at = profile.get("created_at")
    if isinstance(created_at, str):
        with contextlib.suppress(ValueError):
            created = int(datetime.fromisoformat(created_at).timestamp())
    return {
        "id": profile.get("name") or profile_id,
        "voice_id": profile_id,
        "name": profile.get("name") or profile_id,
        "object": "voice",
        "owned_by": "omnivoice-server",
        "filename": "ref_audio.wav",
        "ref_text": profile.get("ref_text") or "",
        "embedding": False,
        "created": created,
    }


@router.get("/audio/voices")
async def list_audio_voices(profile_svc: ProfileService = Depends(_get_profiles)):
    """OpenAI/faster-qwen3-tts compatible voice listing."""
    configured = [
        {
            "id": preset,
            "voice_id": preset,
            "name": preset,
            "object": "voice",
            "owned_by": "omnivoice-server",
            "embedding": False,
        }
        for preset in sorted(OPENAI_VOICE_PRESETS)
    ]
    configured.append(
        {
            "id": "auto",
            "voice_id": "auto",
            "name": "auto",
            "object": "voice",
            "owned_by": "omnivoice-server",
            "embedding": False,
        }
    )
    data = configured + [_audio_voice_item(profile) for profile in profile_svc.list_profiles()]
    return {"object": "list", "data": data}


def _resolve_audio_profile(profile_svc: ProfileService, voice_id: str) -> tuple[str, dict]:
    try:
        profile_id = profile_svc.resolve_profile_id(voice_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Voice {voice_id!r} not found")
    profile = next(
        (item for item in profile_svc.list_profiles() if item["profile_id"] == profile_id),
        None,
    )
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Voice {voice_id!r} not found")
    return profile_id, profile


def _validate_voice_name(
    profile_svc: ProfileService,
    name: str,
    *,
    exclude_profile_id: str | None = None,
) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Voice name cannot be empty")
    if len(cleaned) > 128:
        raise HTTPException(status_code=400, detail="Voice name exceeds 128 characters")
    folded = cleaned.casefold()
    if folded in OPENAI_VOICE_PRESETS or folded == "auto":
        raise HTTPException(status_code=409, detail="Voice name conflicts with a built-in voice")
    if cleaned.lower().startswith(("clone:", "design:")):
        raise HTTPException(status_code=409, detail="Voice name uses a reserved prefix")
    for profile in profile_svc.list_profiles():
        if profile["profile_id"] == exclude_profile_id:
            continue
        existing_names = {
            str(value).casefold()
            for value in (profile["profile_id"], profile.get("name"))
            if value
        }
        if folded in existing_names:
            raise HTTPException(status_code=409, detail="Voice name is already in use")
    return cleaned


@router.get("/audio/voices/{voice_id}")
async def get_audio_voice(
    voice_id: str,
    profile_svc: ProfileService = Depends(_get_profiles),
):
    if voice_id in OPENAI_VOICE_PRESETS or voice_id == "auto":
        return {
            "id": voice_id,
            "voice_id": voice_id,
            "name": voice_id,
            "object": "voice",
            "owned_by": "omnivoice-server",
            "embedding": False,
        }
    _, profile = _resolve_audio_profile(profile_svc, voice_id)
    return _audio_voice_item(profile)


@router.patch("/audio/voices/{voice_id}")
async def update_audio_voice(
    voice_id: str,
    update: VoiceUpdate,
    request: Request,
    profile_svc: ProfileService = Depends(_get_profiles),
    model_svc: ModelService = Depends(_get_model),
):
    if voice_id in OPENAI_VOICE_PRESETS or voice_id == "auto":
        raise HTTPException(status_code=403, detail="Built-in voices cannot be modified")
    profile_id, _ = _resolve_audio_profile(profile_svc, voice_id)
    if update.name is not None:
        update.name = _validate_voice_name(
            profile_svc,
            update.name,
            exclude_profile_id=profile_id,
        )
    try:
        updated = profile_svc.update_metadata(
            profile_id,
            name=update.name,
            ref_text=update.ref_text,
            update_name="name" in update.model_fields_set,
            update_ref_text="ref_text" in update.model_fields_set,
        )
    except (ProfileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    model_svc.invalidate_voice_clone_prompt(profile_id)
    return _audio_voice_item(updated)


@router.delete("/audio/voices/{voice_id}")
async def delete_audio_voice(
    voice_id: str,
    request: Request,
    profile_svc: ProfileService = Depends(_get_profiles),
):
    if voice_id in OPENAI_VOICE_PRESETS or voice_id == "auto":
        raise HTTPException(status_code=403, detail="Built-in voices cannot be modified")
    profile_id, _ = _resolve_audio_profile(profile_svc, voice_id)
    profile_svc.delete_profile(profile_id)
    request.app.state.model_svc.invalidate_voice_clone_prompt(profile_id)
    return {"deleted": True, "voice_id": profile_id, "files": ["ref_audio.wav", "meta.json"]}


@compat_router.post("/upload_voice")
@compat_router.post("/v1/upload_voice")
async def upload_voice_compat(
    request: Request,
    voice_file: UploadFile | None = File(default=None),
    voice_url: str | None = Form(default=None),
    name: str | None = Form(default=None),
    voice_name: str | None = Form(default=None),
    ref_text: str | None = Form(default=None),
    reference_text: str | None = Form(default=None),
    data: str | None = Form(default=None),
    profile_svc: ProfileService = Depends(_get_profiles),
    model_svc: ModelService = Depends(_get_model),
):
    """Compatibility upload endpoint used by faster-qwen3-tts clients."""
    from ..utils.audio import read_upload_bounded, validate_audio_bytes

    cfg = request.app.state.cfg
    metadata = {}
    if data:
        try:
            metadata = json.loads(data)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid data JSON: {exc}")
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=400, detail="data must be a JSON object")
    metadata_ref_text = metadata.get("ref_text")
    metadata_name = metadata.get("name")
    if metadata_ref_text is not None and not isinstance(metadata_ref_text, str):
        raise HTTPException(status_code=400, detail="data.ref_text must be a string")
    if metadata_name is not None and not isinstance(metadata_name, str):
        raise HTTPException(status_code=400, detail="data.name must be a string")
    final_ref_text = (ref_text or reference_text or metadata_ref_text or "").strip() or None
    final_name = (name or voice_name or metadata_name or "").strip() or None
    if final_ref_text and len(final_ref_text) > 10_000:
        raise HTTPException(status_code=400, detail="Reference text exceeds 10000 characters")
    if final_name:
        final_name = _validate_voice_name(profile_svc, final_name)
    if not voice_file and not voice_url:
        raise HTTPException(status_code=400, detail="voice_url or voice_file is required")

    downloaded_path: str | None = None
    try:
        if voice_url:
            from .speech import _download_voice_url

            try:
                downloaded_path = await _download_voice_url(
                    voice_url,
                    cfg.max_ref_audio_bytes,
                    allow_private=cfg.allow_private_voice_urls,
                )
                raw = Path(downloaded_path).read_bytes()
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Failed to download voice_url: {exc}")
        else:
            assert voice_file is not None
            raw = await voice_file.read(cfg.max_ref_audio_bytes + 1)
        try:
            audio_bytes = read_upload_bounded(raw, cfg.max_ref_audio_bytes)
            validate_audio_bytes(audio_bytes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        voice_id = uuid.uuid4().hex
        profile_svc.save_profile(
            voice_id,
            audio_bytes,
            ref_text=final_ref_text,
            name=final_name,
        )
        model_svc.invalidate_voice_clone_prompt(voice_id)
        return {"voice_id": voice_id, "id": final_name or voice_id, "name": final_name or voice_id}
    finally:
        if downloaded_path:
            with contextlib.suppress(OSError):
                Path(downloaded_path).unlink()
