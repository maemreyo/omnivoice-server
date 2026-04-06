"""
Server configuration.
Priority: CLI flags > env vars > defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

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
    port: int = Field(default=8880, ge=1, le=65535)
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    # Model
    model_id: str = Field(
        default="k2-fsa/OmniVoice",
        description="HuggingFace repo ID or local path",
    )
    device: Literal["auto", "cuda", "mps", "cpu"] = "cpu"  # MPS broken - use CPU
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
            "Temperature for token sampling at each step. "
            "0=greedy, higher=more randomness."
        ),
    )

    # Inference
    max_concurrent: int = Field(
        default=2,
        ge=1,
        le=16,
        description=(
            "Without batching: max simultaneous single-request inference calls "
            "(controls both thread pool size and semaphore). "
            "With batching: max simultaneous batch dispatches to the GPU "
            "(controls thread pool size; typically 1 is enough for a single GPU)."
        ),
    )
    request_timeout_s: int = Field(
        default=120,
        description="Max seconds per synthesis request before 504",
    )

    # Dynamic batching
    batch_enabled: bool = Field(
        default=True,
        description="Enable dynamic batching of concurrent requests",
    )
    batch_max_size: int = Field(
        default=8,
        ge=1,
        le=64,
        description="Max requests to batch together in a single model.generate() call",
    )
    batch_timeout_ms: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Max milliseconds to wait for more requests before dispatching a batch",
    )

    # Audio cache
    cache_enabled: bool = Field(
        default=True,
        description="Enable in-memory LRU cache for repeated synthesis requests",
    )
    cache_max_mb: int = Field(
        default=512,
        ge=16,
        le=8192,
        description="Max memory for audio cache in MB. LRU eviction when exceeded.",
    )
    cache_ttl_s: int = Field(
        default=3600,
        ge=0,
        description="Cache entry TTL in seconds. 0 = no expiry (LRU eviction only).",
    )

    # Voice profiles
    profile_dir: Path = Field(
        default=Path.home() / ".omnivoice" / "profiles",
        description="Directory for saved voice cloning profiles",
    )

    # Auth
    api_key: str = Field(
        default="",
        description="Optional Bearer token. Empty = no auth.",
    )

    # Streaming
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

    # FIX: was defined twice — removed duplicate. Single source of truth here.
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
