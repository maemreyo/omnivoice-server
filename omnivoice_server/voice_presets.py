"""Canonical OmniVoice design attributes and local preset voice mappings."""

from __future__ import annotations

DEFAULT_DESIGN_INSTRUCTIONS = "male, middle-aged, moderate pitch, british accent"

# OpenAI-compatible preset names mapped to local OmniVoice design prompts.
# These are local heuristic presets for compatibility, not official voice clones.
OPENAI_VOICE_PRESETS = {
    "alloy": "female, young adult, moderate pitch, american accent",
    "ash": "male, young adult, low pitch, american accent",
    "ballad": "male, middle-aged, low pitch, british accent",
    "cedar": "male, middle-aged, low pitch, american accent",
    "coral": "female, young adult, high pitch, australian accent",
    "echo": "male, middle-aged, moderate pitch, canadian accent",
    "fable": "female, middle-aged, moderate pitch, british accent",
    "marin": "female, middle-aged, moderate pitch, canadian accent",
    "nova": "female, young adult, high pitch, american accent",
    "onyx": "male, middle-aged, very low pitch, british accent",
    "sage": "female, elderly, low pitch, british accent",
    "shimmer": "female, young adult, very high pitch, american accent",
    "verse": "male, young adult, moderate pitch, british accent",
}


def get_openai_voice_preset(name: str | None) -> str | None:
    if name is None:
        return None
    return OPENAI_VOICE_PRESETS.get(name.strip().lower())


def is_openai_voice_preset(name: str | None) -> bool:
    return get_openai_voice_preset(name) is not None


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
