"""
Voice definitions stored as plain .txt files in a directory.

Motivation (issue #38): OpenAI-compatible clients send a bare `voice` string and
have no way to pass `instructions`. A voice design therefore cannot be expressed
through them at all. Dropping a file into the voice directory gives that design
a name, and the name is all a client needs to send.

File format — deliberately forgiving, since these are hand-written:

    # studio-narrator.txt
    male, middle-aged, low pitch, british accent
    seed: 4242
    speed: 0.95

Any line matching `key: value` (or `key = value`) whose key is a known parameter
sets that parameter. Every other non-comment line is part of the voice design
description. Lines starting with `#` are comments.

The design attributes are validated the same way the `instructions` field is, so
a typo surfaces as a startup warning and a missing voice rather than as strange
audio.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..utils.instruction_validation import (
    InstructionValidationError,
    validate_and_canonicalize_instructions,
)

logger = logging.getLogger(__name__)

VOICE_FILE_SUFFIX = ".txt"

# Mirrors the profile_id rule so a voice name is always safe in a URL path.
_VALID_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

_SETTING_LINE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[:=]\s*(.+?)\s*$")

# Parameters a voice file may pin, and how to coerce them. Restricted to the
# ones that shape the voice itself — a file should not be able to set, say,
# response_format, which belongs to the caller.
_INT_KEYS = {"seed", "num_step"}
_FLOAT_KEYS = {
    "speed",
    "guidance_scale",
    "t_shift",
    "position_temperature",
    "class_temperature",
    "duration",
}
_BOOL_KEYS = {"denoise"}
_STR_KEYS = {"language"}
_META_KEYS = {"instructions", "description"}

KNOWN_KEYS = _INT_KEYS | _FLOAT_KEYS | _BOOL_KEYS | _STR_KEYS | _META_KEYS

_TRUE = {"true", "yes", "on", "1"}
_FALSE = {"false", "no", "off", "0"}


class VoiceFileError(Exception):
    """A voice file exists but cannot be used."""


@dataclass(frozen=True)
class VoiceFile:
    name: str
    instructions: str
    description: str | None = None
    params: dict = field(default_factory=dict)
    source: Path | None = None


def _coerce(key: str, raw: str) -> object:
    if key in _INT_KEYS:
        return int(raw)
    if key in _FLOAT_KEYS:
        return float(raw)
    if key in _BOOL_KEYS:
        lowered = raw.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ValueError(f"expected true/false, got {raw!r}")
    return raw


def parse_voice_file(text: str, name: str) -> VoiceFile:
    """
    Parse voice-file content. Raises VoiceFileError with a message naming the
    problem, so callers can log something a human can act on.
    """
    instruction_lines: list[str] = []
    params: dict = {}
    description: str | None = None
    explicit_instructions: str | None = None

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = _SETTING_LINE.match(stripped)
        key = match.group(1).lower() if match else None

        if key in KNOWN_KEYS:
            value = match.group(2)  # type: ignore[union-attr]
            if key == "description":
                description = value
                continue
            if key == "instructions":
                explicit_instructions = value
                continue
            try:
                params[key] = _coerce(key, value)
            except ValueError as e:
                raise VoiceFileError(f"line {lineno}: invalid value for '{key}' — {e}") from e
            continue

        if key is not None:
            # Looks like a setting but names nothing we know. Silently treating
            # it as voice attributes would produce a confusing validation error
            # pointing at the wrong thing.
            raise VoiceFileError(
                f"line {lineno}: unknown setting '{key}'. "
                f"Known settings: {', '.join(sorted(KNOWN_KEYS))}"
            )

        instruction_lines.append(stripped)

    raw_instructions = explicit_instructions or ", ".join(instruction_lines)
    if not raw_instructions:
        raise VoiceFileError("no voice attributes found")

    try:
        instructions = validate_and_canonicalize_instructions(raw_instructions)
    except InstructionValidationError as e:
        raise VoiceFileError(str(e)) from e

    return VoiceFile(
        name=name,
        instructions=instructions,
        description=description,
        params=params,
    )


class VoiceFileService:
    """
    Reads voice files from disk, caching parsed results by mtime.

    Files are re-read when they change, so a voice can be added or edited
    without restarting the server — which is the point of putting them in a
    directory rather than in config.
    """

    def __init__(self, voice_dir: Path) -> None:
        self._dir = voice_dir
        self._cache: dict[Path, tuple[float, int, VoiceFile | None]] = {}

    @property
    def directory(self) -> Path:
        return self._dir

    def _load(self, path: Path) -> VoiceFile | None:
        """Parse one file, or return None if it is unusable. Never raises."""
        try:
            stat = path.stat()
        except OSError as e:
            logger.warning("Cannot stat voice file %s: %s", path, e)
            return None

        cached = self._cache.get(path)
        if cached is not None and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]

        name = path.stem
        parsed: VoiceFile | None = None

        if not _VALID_NAME.match(name):
            logger.warning(
                "Ignoring voice file %s: name must be 1-64 characters of "
                "letters, digits, dashes or underscores.",
                path.name,
            )
        else:
            try:
                parsed = parse_voice_file(path.read_text(encoding="utf-8"), name)
                parsed = VoiceFile(
                    name=parsed.name,
                    instructions=parsed.instructions,
                    description=parsed.description,
                    params=parsed.params,
                    source=path,
                )
            except (VoiceFileError, OSError, UnicodeDecodeError) as e:
                logger.warning("Ignoring voice file %s: %s", path.name, e)

        self._cache[path] = (stat.st_mtime, stat.st_size, parsed)
        return parsed

    def list_voices(self) -> list[VoiceFile]:
        """Every usable voice file, sorted by name. Unusable ones are skipped."""
        if not self._dir.is_dir():
            return []

        voices = []
        for path in sorted(self._dir.glob(f"*{VOICE_FILE_SUFFIX}")):
            if not path.is_file():
                continue
            voice = self._load(path)
            if voice is not None:
                voices.append(voice)
        return voices

    def get(self, name: str) -> VoiceFile | None:
        """Look up one voice by name. Case-insensitive, like the other voices."""
        if not name or not _VALID_NAME.match(name):
            return None
        if not self._dir.is_dir():
            return None

        path = self._dir / f"{name}{VOICE_FILE_SUFFIX}"
        if path.is_file():
            return self._load(path)

        # Fall back to a case-insensitive scan; OpenAI voice names are lowercase
        # by convention but a file might not be.
        lowered = name.lower()
        for candidate in self._dir.glob(f"*{VOICE_FILE_SUFFIX}"):
            if candidate.stem.lower() == lowered and candidate.is_file():
                return self._load(candidate)
        return None
