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
import os
import shutil
import tempfile
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

    def resolve_profile_id(self, identifier: str) -> str:
        """Resolve an exact profile ID or a stored display name."""
        try:
            exact = self._profile_path(identifier)
        except ValueError:
            exact = None
        if exact is not None and (exact / PROFILE_AUDIO_FILE).exists():
            return exact.name
        matches = [
            profile["profile_id"]
            for profile in self.list_profiles()
            if profile.get("name") == identifier
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Voice name '{identifier}' is ambiguous")
        raise ProfileNotFoundError(f"Profile '{identifier}' not found")

    def update_metadata(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        ref_text: str | None = None,
        update_name: bool = False,
        update_ref_text: bool = False,
    ) -> dict:
        """Update editable metadata without rewriting reference audio."""
        profile_path = self._profile_path(profile_id)
        audio_path = profile_path / PROFILE_AUDIO_FILE
        if not audio_path.exists():
            raise ProfileNotFoundError(f"Profile '{profile_id}' not found")
        meta = self._read_meta(profile_path) or {}
        if update_name:
            cleaned_name = (name or "").strip()
            if not cleaned_name:
                raise ValueError("Voice name cannot be empty")
            meta["name"] = cleaned_name
        if update_ref_text:
            meta["ref_text"] = (ref_text or "").strip() or None
        self._write_atomic(
            profile_path / PROFILE_META_FILE,
            json.dumps(meta, ensure_ascii=False, indent=2).encode(),
        )
        return {"profile_id": profile_id, **meta}

    def update_profile(
        self,
        profile_id: str,
        *,
        audio_bytes: bytes | None = None,
        ref_text: str | None = None,
        update_ref_text: bool = False,
    ) -> dict:
        """Update profile content while preserving metadata not being changed."""
        profile_path = self._profile_path(profile_id)
        audio_path = profile_path / PROFILE_AUDIO_FILE
        if not audio_path.exists():
            raise ProfileNotFoundError(f"Profile '{profile_id}' not found")

        stored_meta = self._read_meta(profile_path)
        meta = stored_meta or {
            "name": profile_id,
            "ref_text": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if audio_bytes is not None:
            self._write_atomic(audio_path, audio_bytes)
        if update_ref_text:
            meta["ref_text"] = (ref_text or "").strip() or None
        if update_ref_text or stored_meta is None:
            self._write_atomic(
                profile_path / PROFILE_META_FILE,
                json.dumps(meta, ensure_ascii=False, indent=2).encode(),
            )
        return {"profile_id": profile_id, **meta}

    def save_profile(
        self,
        profile_id: str,
        audio_bytes: bytes,
        ref_text: str | None = None,
        overwrite: bool = False,
        name: str | None = None,
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

        newly_created = not profile_path.exists()
        profile_path.mkdir(parents=True, exist_ok=True)

        try:
            # Write audio
            audio_path = profile_path / PROFILE_AUDIO_FILE
            self._write_atomic(audio_path, audio_bytes)

            # Write metadata
            now = datetime.now(timezone.utc).isoformat()
            meta = {
                "name": name or profile_id,
                "ref_text": ref_text,
                "created_at": now,
            }
            self._write_atomic(
                profile_path / PROFILE_META_FILE,
                json.dumps(meta, ensure_ascii=False, indent=2).encode(),
            )
        except Exception:
            if newly_created:
                shutil.rmtree(profile_path, ignore_errors=True)
            raise

        logger.info(f"Saved profile '{profile_id}'")
        return {"profile_id": profile_id, **meta}

    def delete_profile(self, profile_id: str) -> None:
        profile_path = self._profile_path(profile_id)
        if not profile_path.exists():
            raise ProfileNotFoundError(f"Profile '{profile_id}' not found")
        shutil.rmtree(profile_path)
        logger.info(f"Deleted profile '{profile_id}'")

    def _profile_path(self, profile_id: str) -> Path:
        # Reject rather than rewrite invalid IDs: rewriting could target a
        # different valid profile (for example, "voice!" -> "voice").
        safe = "".join(c for c in profile_id if c.isalnum() or c in "-_")
        if not safe or safe != profile_id:
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

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        """Replace one profile file without exposing partial contents."""
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(data)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            temp_path.replace(path)
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
