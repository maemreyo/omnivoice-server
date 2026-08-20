"""
Server configuration.
Priority: CLI flags > env vars > defaults.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import platformdirs
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    import torch


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OMNIVOICE_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Server
    host: str = Field(default="127.0.0.1", description="Bind host")
    port: int = Field(default=8880, ge=0, le=65535)
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    # Model
    model_id: str = Field(
        default="k2-fsa/OmniVoice",
        description="HuggingFace repo ID or local path",
    )
    model_cache_dir: Path | None = Field(
        default=None,
        description="Override HuggingFace model cache directory",
    )
    device: Literal["auto", "cuda", "mps", "cpu"] = "cpu"
    num_step: int = Field(default=32, ge=1, le=64)  # Upstream default

    # Advanced generation params (passed through to OmniVoice.generate())
    # Expose the ones users are likely to tune; leave the rest at upstream defaults.
    guidance_scale: float = Field(
        default=2.0,
        ge=0.0,
        le=10.0,
        description="CFG scale. Higher = stronger voice conditioning.",
    )
    denoise: bool = Field(
        default=True,
        description="Enable upstream denoising token. Recommended on.",
    )
    t_shift: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,  # Upstream docs don't specify max; allowing up to 2.0 for flexibility
        description="Noise schedule shift. Affects quality/speed tradeoff.",
    )
    position_temperature: float = Field(
        default=5.0,
        ge=0.0,
        le=10.0,
        description=(
            "Temperature for mask-position selection. "
            "0=deterministic/greedy, higher=more diversity."
        ),
    )
    class_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description=(
            "Temperature for token sampling at each step. 0=greedy, higher=more randomness."
        ),
    )

    # Inference
    max_concurrent: int = Field(
        default=2,
        ge=1,
        le=16,
        description="Max simultaneous inference calls",
    )
    request_timeout_s: int = Field(
        default=120,
        description="Max seconds per synthesis request before 504",
    )
    cleanup_interval: int = Field(
        default=0,
        ge=0,
        le=10_000,
        description="Run hot-path memory cleanup every N syntheses. 0 disables it.",
    )
    cuda_alloc_conf: str = Field(
        default="expandable_segments:True",
        description=(
            "Value to apply to PYTORCH_CUDA_ALLOC_CONF before CUDA initialization. "
            "Use empty/off/disabled to skip the override."
        ),
    )
    offload_voice_encoder: bool = Field(
        default=True,
        description=(
            "Keep OmniVoice reference-encoder modules on CPU between voice preparations "
            "when the installed model exposes compatible modules."
        ),
    )
    skip_voice_encoder: bool = Field(
        default=True,
        description=(
            "Request skip_encoder=True from patched OmniVoice builds; automatically falls "
            "back to the standard loader when unsupported."
        ),
    )
    low_vram_mode: bool = Field(
        default=False,
        description=(
            "Opt in to the vendored OmniVoice 0.1.2 decoder-only tokenizer loader; "
            "incompatible models automatically use the standard loader."
        ),
    )
    flashinfer_mode: bool = Field(
        default=False,
        description=(
            "Opt in to the vendored FlashInfer decoder patch; unavailable or incompatible "
            "installations fall back to the standard OmniVoice forward path."
        ),
    )
    flashinfer_cuda_graph: bool = Field(
        default=False,
        description="Use FlashInfer CUDA graphs for fixed-shape, single-request decoding.",
    )
    split_cfg_batch: bool = Field(
        default=False,
        description=(
            "Run conditional and unconditional CFG branches separately to reduce "
            "peak VRAM when FlashInfer is unavailable."
        ),
    )
    cuda_tf32: bool = Field(
        default=True,
        description="Enable CUDA TF32 matmul fast paths where supported.",
    )
    transcriber: Literal["whisper", "faster-whisper"] = Field(
        default="whisper",
        description="Reference-audio transcription backend when ref_text is omitted.",
    )
    asr_model_name: str = Field(
        default="large-v3-turbo",
        description="Whisper or Faster-Whisper model name for automatic reference transcription.",
    )
    asr_device: Literal["auto", "cuda", "cpu"] = Field(
        default="cpu",
        description="Device for optional automatic reference transcription.",
    )
    asr_language: str | None = Field(
        default=None,
        description="Optional language code for automatic reference transcription.",
    )
    asr_beam_size: int = Field(default=5, ge=1, le=20)
    shutdown_timeout: int = Field(
        default=10,
        ge=1,
        le=300,
        description="Seconds to wait for in-flight requests on shutdown",
    )

    # Voice profiles
    profile_dir: Path = Field(
        default=Path(platformdirs.user_data_dir("omnivoice")) / "profiles",
        description="Directory for saved voice cloning profiles",
    )

    # Auth
    api_key: str = Field(
        default="",
        description="Optional Bearer token. Empty = no auth.",
    )

    # CORS
    cors_allow_origins: list[str] = Field(
        default=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5001",
            "http://127.0.0.1:5001",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        description="Allowed CORS origins for browser clients.",
    )
    cors_allow_credentials: bool = Field(
        default=False,
        description="Allow credentialed CORS requests. Requires explicit origins.",
    )

    # Streaming
    stream: bool = Field(
        default=False,
        description="Force-enable sentence-level streaming for all requests.",
    )
    stream_overlap: bool = Field(
        default=False,
        description="Enable overlapped producer-consumer sentence streaming.",
    )
    stream_chunk_max_chars: int = Field(
        default=400,
        description="Max chars per sentence chunk when streaming",
    )

    max_ref_audio_mb: int = Field(
        default=25,
        ge=1,
        le=200,
        description="Max upload size for ref_audio files in megabytes.",
    )
    allow_private_voice_urls: bool = Field(
        default=False,
        description="Allow voice_url downloads from loopback or private network addresses.",
    )

    default_voice: str = Field(
        default="female, british accent",
        description=(
            "Default voice description used when no voice is specified for a speaker. "
            "Deployers can customise this for non-English use cases."
        ),
    )

    @property
    def max_ref_audio_bytes(self) -> int:
        """Return max upload size in bytes."""
        return self.max_ref_audio_mb * 1024 * 1024

    @field_validator("device")
    @classmethod
    def resolve_auto_device(cls, v: str) -> str:
        if v != "auto":
            return v
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            if torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def parse_cors_allow_origins(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if not isinstance(parsed, list):
                    raise ValueError("cors_allow_origins must be a list of strings")
                return parsed
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @field_validator("cors_allow_credentials")
    @classmethod
    def validate_cors_credentials(cls, value: bool, info):
        origins = info.data.get("cors_allow_origins", [])
        if value and "*" in origins:
            raise ValueError(
                "cors_allow_credentials cannot be true when cors_allow_origins includes '*'"
            )
        return value

    @field_validator("cuda_alloc_conf")
    @classmethod
    def normalize_cuda_alloc_conf(cls, v: str) -> str:
        value = (v or "").strip()
        if value.lower() in {"", "off", "none", "disable", "disabled"}:
            return ""
        return value

    @property
    def torch_dtype(self) -> torch.dtype:
        """Return appropriate torch dtype for device."""
        import torch

        if self.device in ("cuda", "mps"):
            return torch.float16
        return torch.float32

    @property
    def torch_device_map(self) -> str:
        """Map to device string for OmniVoice.from_pretrained()."""
        if self.device == "cuda":
            return "cuda:0"
        return self.device  # "mps" or "cpu"
