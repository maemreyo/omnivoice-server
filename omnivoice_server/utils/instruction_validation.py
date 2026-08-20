"""Instruction validation and canonicalization for voice design attributes."""

from __future__ import annotations

from ..voice_presets import DESIGN_ATTRIBUTES

# Accent short-form aliases that should be canonicalized to full form
ACCENT_ALIASES = {
    "american": "american accent",
    "british": "british accent",
    "australian": "australian accent",
    "chinese": "chinese accent",
    "canadian": "canadian accent",
    "indian": "indian accent",
    "korean": "korean accent",
    "portuguese": "portuguese accent",
    "russian": "russian accent",
    "japanese": "japanese accent",
}

# Build flat set of all supported attributes
SUPPORTED_ATTRIBUTES: set[str] = set()
for category_values in DESIGN_ATTRIBUTES.values():
    SUPPORTED_ATTRIBUTES.update(category_values)

# Add accent aliases to supported set
SUPPORTED_ATTRIBUTES.update(ACCENT_ALIASES.keys())

# Unsupported emotion attributes (explicitly rejected)
UNSUPPORTED_EMOTIONS = {
    "cheerful",
    "sad",
    "angry",
    "surprised",
    "happy",
    "fearful",
    "disgusted",
}

# Unsupported speaking style attributes (explicitly rejected)
UNSUPPORTED_STYLES = {
    "narration",
    "customer_service",
    "news_presentation",
    "sportscasting",
}

# Category conflict detection
CONFLICT_CATEGORIES = {
    "gender": {"male", "female"},
    "age": {"child", "teenager", "young adult", "middle-aged", "elderly"},
    "pitch": {
        "very low pitch",
        "low pitch",
        "moderate pitch",
        "high pitch",
        "very high pitch",
    },
}


class InstructionValidationError(ValueError):
    """Raised when instruction validation fails."""

    def __init__(self, message: str, invalid_attrs: list[str] | None = None):
        super().__init__(message)
        self.invalid_attrs = invalid_attrs or []


def validate_and_canonicalize_instructions(instructions: str) -> str:
    """
    Validate and canonicalize voice design instructions.

    Args:
        instructions: Comma-separated voice design attributes

    Returns:
        Canonicalized instruction string with aliases expanded

    Raises:
        InstructionValidationError: If validation fails
    """
    if not instructions or not instructions.strip():
        raise InstructionValidationError("Instructions cannot be empty")

    # Parse and normalize
    attrs = [attr.strip().lower() for attr in instructions.split(",")]
    attrs = [attr for attr in attrs if attr]  # Remove empty strings

    if not attrs:
        raise InstructionValidationError("Instructions cannot be empty")

    # Check for unsupported emotion attributes
    unsupported = [attr for attr in attrs if attr in UNSUPPORTED_EMOTIONS]
    if unsupported:
        raise InstructionValidationError(
            f"Unsupported emotion attributes: {', '.join(unsupported)}. "
            f"OmniVoice does not support emotion-based voice design.",
            invalid_attrs=unsupported,
        )

    # Check for unsupported speaking style attributes
    unsupported_styles = [attr for attr in attrs if attr in UNSUPPORTED_STYLES]
    if unsupported_styles:
        raise InstructionValidationError(
            f"Unsupported speaking style attributes: {', '.join(unsupported_styles)}. "
            f"OmniVoice does not support speaking style modifiers.",
            invalid_attrs=unsupported_styles,
        )

    # Canonicalize accent aliases
    canonicalized = []
    for attr in attrs:
        if attr in ACCENT_ALIASES:
            canonicalized.append(ACCENT_ALIASES[attr])
        else:
            canonicalized.append(attr)

    # Check for unsupported attributes (after canonicalization)
    unsupported_attrs = [attr for attr in canonicalized if attr not in SUPPORTED_ATTRIBUTES]
    if unsupported_attrs:
        raise InstructionValidationError(
            f"Unsupported attributes: {', '.join(unsupported_attrs)}. "
            f"See /v1/voices for supported design attributes.",
            invalid_attrs=unsupported_attrs,
        )

    # Deduplicate while preserving order
    seen = set()
    deduplicated = []
    for attr in canonicalized:
        if attr not in seen:
            seen.add(attr)
            deduplicated.append(attr)

    # Check for conflicts within categories
    for category_name, category_values in CONFLICT_CATEGORIES.items():
        found = [attr for attr in deduplicated if attr in category_values]
        if len(found) > 1:
            raise InstructionValidationError(
                f"Conflicting {category_name} attributes: {', '.join(found)}. "
                f"Only one {category_name} attribute is allowed.",
                invalid_attrs=found,
            )

    return ",".join(deduplicated)
