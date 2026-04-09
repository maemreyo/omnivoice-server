"""
/v1/voices                    — list all available voices
/v1/voices/profiles           — manage cloning profiles
/v1/voices/profiles/{id}      — get/patch/delete specific profile
"""

from __future__ import annotations

import logging

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

from ..services.profiles import (
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
    ProfileService,
)

logger = logging.getLogger(__name__)
router = APIRouter()

DESIGN_ATTRIBUTES = {
    "gender": ["male", "female"],
    "age": ["child", "teenager", "young adult", "middle-aged", "elderly"],
    "pitch": [
        "very low pitch",
        "low pitch",
        "moderate pitch",
        "high pitch",
        "very high pitch",
    ],
    "style": ["whisper"],
    "accent_en": [
        "american accent",
        "british accent",
        "australian accent",
        "chinese accent",
        "canadian accent",
        "indian accent",
        "korean accent",
        "portuguese accent",
        "russian accent",
        "japanese accent",
    ],
    "dialect_zh": [
        "河南话",
        "陕西话",
        "四川话",
        "贵州话",
        "云南话",
        "桂林话",
        "济南话",
        "石家庄话",
        "甘肃话",
        "宁夏话",
        "青岛话",
        "东北话",
    ],
}


def _get_profiles(request: Request) -> ProfileService:
    return request.app.state.profile_svc


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
                "Ignored by /v1/audio/speech; server default design prompt is "
                "male, middle-aged, moderate pitch, british accent"
            ),
        },
        {
            "id": "design:<attributes>",
            "type": "design",
            "description": "Voice design via attributes. Example: 'design:female,british accent'",
            "attributes_reference": DESIGN_ATTRIBUTES,
        },
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
):
    """
    Save a voice cloning profile.
    Use /v1/audio/speech/clone for synthesis with reference audio uploads.
    """
    from ..utils.audio import read_upload_bounded, validate_audio_bytes

    cfg = request.app.state.cfg  # FIX: was NameError previously

    raw = await ref_audio.read()
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
    profile_id: str,
    profile_svc: ProfileService = Depends(_get_profiles),
):
    try:
        profile_svc.delete_profile(profile_id)
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{profile_id}' not found",
        )


# ── PATCH /v1/voices/profiles/{profile_id} ───────────────────────────────────


@router.patch("/voices/profiles/{profile_id}", status_code=status.HTTP_200_OK)
async def update_profile(
    profile_id: str,
    request: Request,  # FIX: needed for cfg.max_ref_audio_bytes
    ref_audio: UploadFile | None = File(default=None),
    ref_text: str | None = Form(default=None),
    profile_svc: ProfileService = Depends(_get_profiles),
):
    """
    Update an existing profile. Fields not provided are left unchanged.
    """
    # Verify it exists first
    try:
        existing_path = profile_svc.get_ref_audio_path(profile_id)
    except ProfileNotFoundError:
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
        raw = await ref_audio.read()
        try:
            # FIX: PATCH was missing size + format validation entirely
            audio_bytes = read_upload_bounded(raw, cfg.max_ref_audio_bytes)
            validate_audio_bytes(audio_bytes)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(e),
            )
        meta = profile_svc.save_profile(
            profile_id=profile_id,
            audio_bytes=audio_bytes,
            ref_text=ref_text,
            overwrite=True,
        )
    else:
        # Only updating ref_text — keep existing audio
        audio_bytes = existing_path.read_bytes()
        meta = profile_svc.save_profile(
            profile_id=profile_id,
            audio_bytes=audio_bytes,
            ref_text=ref_text,
            overwrite=True,
        )

    return meta
