"""
Manages voice cloning profiles on disk.

Profile structure on disk:
  <profile_dir>/
    <profile_id>/
      ref_audio.wav     <- reference audio
      meta.json         <- {"name": str, "ref_text": str|null, "created_at": str}
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PROFILE_META_FILE = "meta.json"
PROFILE_AUDIO_FILE = "ref_audio.wav"


class ProfileNotFoundError(Exception):
    pass


class ProfileAlreadyExistsError(Exception):
    pass


class ProfileService:
    def __init__(self, profile_dir: Path) -> None:
        self._dir = profile_dir

    def list_profiles(self) -> list[dict]:
        """Return list of profile metadata dicts."""
        profiles = []
        for p in sorted(self._dir.iterdir()) if self._dir.exists() else []:
            if p.is_dir():
                meta = self._read_meta(p)
                if meta:
                    profiles.append({"profile_id": p.name, **meta})
        return profiles

    def get_ref_audio_path(self, profile_id: str) -> Path:
        """Return path to ref audio file. Raises ProfileNotFoundError if missing."""
        logger.debug(f"[TRACE] get_ref_audio_path called: profile_id={profile_id!r}")
        path = self._profile_path(profile_id) / PROFILE_AUDIO_FILE
        logger.debug(f"[TRACE] Looking for audio at: {path}")
        if not path.exists():
            logger.warning(f"[TRACE] Profile audio NOT FOUND: {profile_id!r} at path {path}")
            raise ProfileNotFoundError(f"Profile '{profile_id}' not found")
        logger.info(f"[TRACE] Profile audio found: {profile_id!r} at {path}")
        return path

    def get_ref_text(self, profile_id: str) -> str | None:
        """Return ref_text from profile metadata, or None."""
        logger.debug(f"[TRACE] get_ref_text called: profile_id={profile_id!r}")
        meta = self._read_meta(self._profile_path(profile_id))
        result = meta.get("ref_text") if meta else None
        logger.debug(f"[TRACE] ref_text for {profile_id!r}: {result!r}")
        return result

    def save_profile(
        self,
        profile_id: str,
        audio_bytes: bytes,
        ref_text: str | None = None,
        overwrite: bool = False,
    ) -> dict:
        """
        Save a new profile. Raises ProfileAlreadyExistsError if exists and overwrite=False.
        Returns the saved metadata dict.
        """
        profile_path = self._profile_path(profile_id)
        if profile_path.exists() and not overwrite:
            raise ProfileAlreadyExistsError(
                f"Profile '{profile_id}' already exists. Use overwrite=true to replace."
            )

        profile_path.mkdir(parents=True, exist_ok=True)

        # Write audio
        audio_path = profile_path / PROFILE_AUDIO_FILE
        audio_path.write_bytes(audio_bytes)

        # Write metadata
        now = datetime.now(timezone.utc).isoformat()
        meta = {
            "name": profile_id,
            "ref_text": ref_text,
            "created_at": now,
        }
        (profile_path / PROFILE_META_FILE).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )

        logger.info(f"Saved profile '{profile_id}'")
        return {"profile_id": profile_id, **meta}

    def delete_profile(self, profile_id: str) -> None:
        profile_path = self._profile_path(profile_id)
        if not profile_path.exists():
            raise ProfileNotFoundError(f"Profile '{profile_id}' not found")
        shutil.rmtree(profile_path)
        logger.info(f"Deleted profile '{profile_id}'")

    def _profile_path(self, profile_id: str) -> Path:
        # Sanitize: only allow alphanumeric + dash + underscore
        safe = "".join(c for c in profile_id if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError(f"Invalid profile_id: '{profile_id}'")
        return self._dir / safe

    def _read_meta(self, profile_path: Path) -> dict | None:
        meta_file = profile_path / PROFILE_META_FILE
        if not meta_file.exists():
            return None
        try:
            return json.loads(meta_file.read_text())
        except (json.JSONDecodeError, OSError):
            return None
