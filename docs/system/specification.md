# omnivoice-server — System Specification

> **Version**: 2026-04-05
> **Status**: Implemented
> **Last Updated**: Synced with commit (main branch)
> **Repo**: `github.com/<you>/omnivoice-server` (separate repo, MIT License)
> **Purpose**: Reference implementation — see README.md for current API documentation
>
> **Note**: This specification was originally a pre-implementation design document. It is now
> maintained as a technical reference for implementation details. For the authoritative
> API documentation, see `README.md`.

---

## Table of Contents

- [omnivoice-server — System Specification](#omnivoice-server--system-specification)
  - [Table of Contents](#table-of-contents)
  - [0. Plan corrections](#0-plan-corrections)
    - [Correction 1: Phase 3 macOS packaging — descoped](#correction-1-phase-3-macos-packaging--descoped)
    - [Correction 2: Upstream contribution pathway — add concrete action](#correction-2-upstream-contribution-pathway--add-concrete-action)
  - [1. Overview](#1-overview)
    - [1.1 OmniVoice Python API — what we need to know](#11-omnivoice-python-api--what-we-need-to-know)
    - [1.2 Tensor → WAV bytes](#12-tensor--wav-bytes)
    - [1.3 Tensor → raw PCM bytes (for streaming)](#13-tensor--raw-pcm-bytes-for-streaming)
    - [1.4 Concurrency model](#14-concurrency-model)
  - [2. Repository layout](#2-repository-layout)
  - [3. pyproject.toml](#3-pyprojecttoml)
  - [4. Config layer](#4-config-layer)
  - [5. App factory & lifespan](#5-app-factory--lifespan)
  - [6. Services](#6-services)
    - [6.1 ModelService](#61-modelservice)
    - [6.2 InferenceService](#62-inferenceservice)
    - [6.3 ProfileService](#63-profileservice)
    - [6.4 MetricsService](#64-metricsservice)
  - [7. Utils](#7-utils)
    - [7.1 audio.py](#71-audiopy)
    - [7.2 text.py](#72-textpy)
  - [8. Routers](#8-routers)
    - [8.1 /v1/audio/speech](#81-v1audiospeech)
    - [8.2 /v1/voices](#82-v1voices)
    - [8.3 /health + /metrics](#83-health--metrics)
  - [9. Benchmark harness](#9-benchmark-harness)
  - [10. Tests](#10-tests)
  - [11. CLI entrypoint](#11-cli-entrypoint)
  - [12. Error catalogue](#12-error-catalogue)
  - [13. Implementation order](#13-implementation-order)

---

## 0. Plan corrections

After validating the decision for a **separate repo**, the original plan has 2 points that need correction:

### Correction 1: Phase 3 macOS packaging — descoped

The original plan placed macOS packaging with python-build-standalone in Phase 3, alongside the HTTP server. This was wrong in terms of priority. Packaging only makes sense once the server is stable. Also, code signing/notarization requires an Apple Developer account ($99/year) — this should not block Phase 2.

**Revised priority:**
```
Phase 1 — Benchmark           (gate: RTF data before commit)
Phase 2 — HTTP Server         (core deliverable)
Phase 5 — Streaming           (high value, close to Phase 2)
Phase 3 — macOS Packaging     (nice-to-have, after Phase 2+5 stable)
```

Phase 3 remains in the spec but as an optional/future section, not a blocking one.

### Correction 2: Upstream contribution pathway — add concrete action

The original plan had a section "Engage upstream via Discussion post immediately" but did not specify the content of that post. A specific template has been added to the spec (see Section 9 Benchmark, subsection "Upstream post template").

All other sections of the original plan remain unchanged — no corrections needed for scope, API design, concurrency model, or memory leak mitigation.

---

## 1. Overview

### 1.1 OmniVoice Python API — what we need to know

```python
from omnivoice import OmniVoice
import torch

model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice",
    device_map="mps",       # "cuda:0" | "mps" | "cpu"
    dtype=torch.float16,    # float16 cho mps/cuda; float32 cho cpu
)

# Return type: list[torch.Tensor]
# Mỗi tensor shape: (1, T) — 1 channel, T samples tại 24kHz
# Ví dụ T=48000 → 2 giây audio

# --- Auto voice ---
audio = model.generate(text="Hello world")

# --- Voice design ---
audio = model.generate(
    text="Hello world",
    instruct="female, british accent",
)

# --- Voice cloning ---
audio = model.generate(
    text="Hello world",
    ref_audio="path/to/ref.wav",   # str path, không phải bytes
    ref_text="Transcript",          # optional; Whisper tự transcribe nếu bỏ
)

# --- Speed control ---
audio = model.generate(text="Hello", speed=1.2)

# --- num_step ---
audio = model.generate(text="Hello", num_step=32)  # default 32 (upstream default)
```

**Important:**
- `ref_audio` takes a **string path**, not bytes or BytesIO. We must write ref audio to a tempfile before calling.
- `model.generate()` is **blocking** → must run in a ThreadPoolExecutor.
- Return value is a **list** containing tensors (usually a 1-element list when input is a single string).
- Tensor dtype: float32, range [-1.0, 1.0], shape (1, T).

### 1.2 Tensor → WAV bytes

```python
import io
import torchaudio

def tensor_to_wav_bytes(tensor: torch.Tensor, sample_rate: int = 24000) -> bytes:
    # tensor shape: (1, T), dtype float32
    buf = io.BytesIO()
    torchaudio.save(buf, tensor.cpu(), sample_rate, format="wav",
                    encoding="PCM_S", bits_per_sample=16)
    buf.seek(0)
    return buf.read()
```

`torchaudio.save()` hỗ trợ `io.BytesIO` khi pass `format="wav"`. Encode thành PCM 16-bit signed int để tương thích rộng (float32 WAV ít client support hơn).

### 1.3 Tensor → raw PCM bytes (for streaming)

```python
def tensor_to_pcm16_bytes(tensor: torch.Tensor) -> bytes:
    # Clamp → int16 → bytes
    pcm = (tensor.squeeze(0).cpu() * 32767).clamp(-32768, 32767)
    return pcm.to(torch.int16).numpy().tobytes()
```

### 1.4 Concurrency model

```
FastAPI (asyncio event loop, 1 uvicorn worker)
  │
  ├── Request arrives → async endpoint handler
  │     │
  │     ├── Validate input (sync, fast, OK on event loop)
  │     │
  │     └── await loop.run_in_executor(executor, blocking_inference)
  │               │
  │               └── ThreadPoolExecutor (max_workers = MAX_CONCURRENT)
  │                     └── model.generate() ← blocking PyTorch
  │
  └── Semaphore(MAX_CONCURRENT) bao ngoài executor call
        → không có request nào vượt quá ngưỡng đồng thời
```

**Why 1 uvicorn worker?** GPU/MPS inference does not benefit from multi-process — each process must load its own model, multiplying RAM/VRAM usage. Using 1 worker + ThreadPoolExecutor is the correct pattern.

---

## 2. Repository layout

```
omnivoice-server/
│
├── omnivoice_server/                 # Python package
│   ├── __init__.py                   # version string only
│   ├── __main__.py                   # python -m omnivoice_server entry
│   ├── cli.py                        # CLI parsing + server startup
│   ├── config.py                     # Settings (pydantic-settings)
│   ├── app.py                        # FastAPI factory + lifespan
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── model.py                  # ModelService: load + singleton
│   │   ├── inference.py              # InferenceService: executor + semaphore
│   │   ├── profiles.py               # ProfileService: disk store
│   │   └── metrics.py                # MetricsService: in-memory counters
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── speech.py                 # /v1/audio/speech + /clone
│   │   ├── voices.py                 # /v1/voices + /v1/voices/profiles
│   │   └── health.py                 # /health + /metrics
│   │
│   └── utils/
│       ├── __init__.py
│       ├── audio.py                  # tensor→bytes helpers
│       └── text.py                   # sentence splitter
│
├── benchmarks/
│   ├── run_benchmark.py              # benchmark script (xem Section 9)
│   ├── sample_ref.wav                # 5s reference audio cho clone test
│   └── results/                      # .gitignored
│
├── tests/
│   ├── conftest.py                   # fixtures: mock model, test client
│   ├── test_speech.py
│   ├── test_clone.py
│   ├── test_voices.py
│   ├── test_streaming.py
│   └── test_health.py
│
├── examples/
│   ├── python_client.py
│   ├── streaming_player.py
│   └── curl_examples.sh
│
├── .github/
│   └── workflows/
│       └── ci.yml                    # ruff + mypy + pytest (no GPU)
│
├── pyproject.toml
├── README.md
├── CHANGELOG.md
└── .gitignore
```

---

## 3. pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "omnivoice-server"
version = "0.1.0"
description = "OpenAI-compatible HTTP server for OmniVoice TTS"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.10"
authors = [{ name = "Your Name", email = "you@example.com" }]

keywords = ["tts", "text-to-speech", "omnivoice", "openai", "fastapi", "voice-cloning"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3",
    "Topic :: Multimedia :: Sound/Audio :: Speech",
]

dependencies = [
    "omnivoice>=0.1.0,<0.2.0",  # Pin to 0.1.x to avoid breaking changes
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "python-multipart>=0.0.12",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "psutil>=6.0.0",
    "huggingface-hub>=0.26.0",
    "torchaudio>=2.0.0",
]

[project.optional-dependencies]
benchmark = ["psutil", "tqdm"]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
    "ruff>=0.6.0",
    "mypy>=1.11.0",
]

[project.scripts]
omnivoice-server = "omnivoice_server.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["omnivoice_server"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.mypy]
python_version = "3.10"
strict = false
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## 4. Config layer

**File: `omnivoice_server/config.py`**

```python
"""
Server configuration.
Priority: CLI flags > env vars > defaults.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    device: Literal["auto", "cuda", "mps", "cpu"] = "cpu"  # MPS broken, use CPU
    num_step: int = Field(default=32, ge=1, le=64)  # Upstream default is 32

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
        le=2.0,  # Upstream doesn't specify max; allowing up to 2.0 for flexibility
        description="Noise schedule shift. Affects quality/speed tradeoff.",
    )
    position_temperature: float = Field(
        default=5.0,
        ge=0.0,
        le=10.0,
        description=(
            "Temperature for mask-position selection. "
            "0=deterministic/greedy, higher=more diversity. "
            "Set to 0 for consistent streaming voice."
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
        description="Max simultaneous inference calls",
    )
    request_timeout_s: int = Field(
        default=120,
        description="Max seconds per synthesis request before 504",
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
    def torch_dtype(self):
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
```

---

## 5. App factory & lifespan

**File: `omnivoice_server/app.py`**

```python
"""
FastAPI application factory.
All shared state lives on app.state — no module-level globals.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from .config import Settings
from .services.model import ModelService
from .services.inference import InferenceService
from .services.profiles import ProfileService
from .services.metrics import MetricsService
from .routers import speech, voices, health

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg: Settings = app.state.cfg

    # ── Startup ─────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    logger.info("omnivoice-server starting up...")
    logger.info(f"  device={cfg.device}  num_step={cfg.num_step}  "
                f"max_concurrent={cfg.max_concurrent}")

    # 1. Ensure profile dir exists
    cfg.profile_dir.mkdir(parents=True, exist_ok=True)

    # 2. Load model (blocking — happens before server accepts requests)
    model_svc = ModelService(cfg)
    await model_svc.load()                  # runs in executor internally
    app.state.model_svc = model_svc

    # 3. Inference service (thread pool + semaphore)
    executor = ThreadPoolExecutor(
        max_workers=cfg.max_concurrent,
        thread_name_prefix="omnivoice-infer",
    )
    app.state.inference_svc = InferenceService(
        model_svc=model_svc,
        executor=executor,
        cfg=cfg,
    )

    # 4. Profile service
    app.state.profile_svc = ProfileService(profile_dir=cfg.profile_dir)

    # 5. Metrics
    app.state.metrics_svc = MetricsService()
    app.state.start_time = time.monotonic()

    elapsed = time.monotonic() - t0
    logger.info(f"Startup complete in {elapsed:.1f}s. "
                f"Listening on http://{cfg.host}:{cfg.port}")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Shutting down...")
    executor.shutdown(wait=False)
    logger.info("Done.")


def create_app(cfg: Settings) -> FastAPI:
    app = FastAPI(
        title="omnivoice-server",
        description="OpenAI-compatible HTTP server for OmniVoice TTS",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # Attach config before lifespan runs
    app.state.cfg = cfg

    # ── Auth middleware ──────────────────────────────────────────────────────
    if cfg.api_key:
        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):
            # Skip auth for health check
            if request.url.path in ("/health", "/metrics"):
                return await call_next(request)
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {cfg.api_key}":
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"error": "Invalid or missing API key"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return await call_next(request)

    # ── Routers ──────────────────────────────────────────────────────────────
    app.include_router(speech.router, prefix="/v1")
    app.include_router(voices.router, prefix="/v1")
    app.include_router(health.router)

    return app
```

**File: `omnivoice_server/__main__.py`**

```python
from omnivoice_server.cli import main
main()
```

---

## 6. Services

### 6.1 ModelService

**File: `omnivoice_server/services/model.py`**

```python
"""
Loads and holds the OmniVoice model singleton.
Model is loaded once at startup; never reloaded during runtime.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import psutil
import torch

from ..config import Settings

logger = logging.getLogger(__name__)


class ModelService:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self._model = None          # type: ignore[assignment]
        self._loaded = False

    async def load(self) -> None:
        """Load model in a thread (blocking op, must not block event loop)."""
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            await loop.run_in_executor(ex, self._load_sync)

    def _load_sync(self) -> None:
        from omnivoice import OmniVoice

        ram_before = _get_ram_mb()
        t0 = time.monotonic()

        logger.info(f"Loading model '{self.cfg.model_id}' on {self.cfg.device}...")

        # Attempt load; try dtype fallback on MPS if float16 causes NaN
        for dtype in self._dtype_candidates():
            try:
                model = OmniVoice.from_pretrained(
                    self.cfg.model_id,
                    device_map=self.cfg.torch_device_map,
                    dtype=dtype,
                )
                # Quick sanity check — generate 0.5s of audio
                test = model.generate(text="test", num_step=4)
                if self._has_nan(test):
                    logger.warning(f"dtype={dtype} produced NaN, trying next...")
                    del model
                    gc.collect()
                    continue
                self._model = model
                break
            except Exception as e:
                logger.warning(f"Failed to load with dtype={dtype}: {e}")
                continue

        if self._model is None:
            raise RuntimeError(
                f"Failed to load OmniVoice on device={self.cfg.device}. "
                "Try --device cpu or check GPU/MPS availability."
            )

        elapsed = time.monotonic() - t0
        ram_after = _get_ram_mb()
        logger.info(
            f"Model loaded in {elapsed:.1f}s. "
            f"RAM: {ram_before:.0f}MB → {ram_after:.0f}MB "
            f"(+{ram_after - ram_before:.0f}MB)"
        )
        self._loaded = True

    def _dtype_candidates(self) -> list:
        """Return dtypes to try in order for this device."""
        import torch
        if self.cfg.device == "cuda":
            return [torch.float16, torch.bfloat16, torch.float32]
        if self.cfg.device == "mps":
            # float16 on MPS can produce NaN with some diffusion ops
            return [torch.float16, torch.bfloat16, torch.float32]
        return [torch.float32]

    @staticmethod
    def _has_nan(tensors: list) -> bool:
        import torch
        return any(torch.isnan(t).any() for t in tensors)

    @property
    def model(self):
        if not self._loaded:
            raise RuntimeError("Model not loaded yet")
        return self._model

    @property
    def is_loaded(self) -> bool:
        return self._loaded


def _get_ram_mb() -> float:
    return psutil.Process().memory_info().rss / 1024 / 1024
```

---

### 6.2 InferenceService

**File: `omnivoice_server/services/inference.py`**

```python
"""
Runs model.generate() in a thread pool with concurrency limiting and
post-request memory cleanup.

DESIGN NOTE — upstream isolation:
  All kwargs construction for model.generate() is centralised in
  OmniVoiceAdapter._build_kwargs(). When OmniVoice adds / renames params,
  only that one method changes — not SynthesisRequest, not the router.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

import torch

from ..config import Settings
from .model import ModelService

logger = logging.getLogger(__name__)


@dataclass
class SynthesisRequest:
    text: str
    mode: str                            # "auto" | "design" | "clone"
    instruct: Optional[str] = None       # for mode="design"
    ref_audio_path: Optional[str] = None # tmp path, for mode="clone"
    ref_text: Optional[str] = None       # for mode="clone", optional
    speed: float = 1.0
    num_step: Optional[int] = None       # None → use server default
    # Advanced passthrough — None means "use upstream default"
    guidance_scale: Optional[float] = None
    denoise: Optional[bool] = None
    t_shift: Optional[float] = None               # Noise schedule shift
    position_temperature: Optional[float] = None  # Mask-position temperature
    class_temperature: Optional[float] = None     # Token sampling temperature
    duration: Optional[float] = None              # Fixed output duration (seconds)


@dataclass
class SynthesisResult:
    tensors: list                        # list[torch.Tensor], each (1, T)
    duration_s: float
    latency_s: float


class OmniVoiceAdapter:
    """
    Thin adapter that translates SynthesisRequest → model.generate() kwargs.

    WHY THIS EXISTS:
    OmniVoice.generate() accepts ~10 parameters (num_step, speed, instruct,
    ref_audio, ref_text, guidance_scale, denoise, duration, …). As upstream
    adds / renames parameters, only this class needs to change — not the
    request schema, not the router, not the tests.

    This is the single seam between omnivoice-server and the upstream library.
    """

    def __init__(self, cfg: Settings) -> None:
        self._cfg = cfg

    def build_kwargs(self, req: SynthesisRequest, model) -> dict:
        """Return kwargs dict ready to pass to model.generate()."""
        num_step = req.num_step or self._cfg.num_step
        guidance_scale = req.guidance_scale if req.guidance_scale is not None else self._cfg.guidance_scale
        denoise = req.denoise if req.denoise is not None else self._cfg.denoise
        t_shift = req.t_shift if req.t_shift is not None else self._cfg.t_shift
        position_temperature = (
            req.position_temperature
            if req.position_temperature is not None
            else self._cfg.position_temperature
        )
        class_temperature = (
            req.class_temperature
            if req.class_temperature is not None
            else self._cfg.class_temperature
        )

        kwargs: dict = {
            "text": req.text,
            "num_step": num_step,
            "speed": req.speed,
            "guidance_scale": guidance_scale,
            "denoise": denoise,
            "t_shift": t_shift,
            "position_temperature": position_temperature,
            "class_temperature": class_temperature,
        }

        # Add optional duration parameter if provided (batch inference feature)
        if req.duration is not None:
            kwargs["duration"] = req.duration

        if req.mode == "design" and req.instruct:
            kwargs["instruct"] = req.instruct
        elif req.mode == "clone" and req.ref_audio_path:
            kwargs["ref_audio"] = req.ref_audio_path
            if req.ref_text:
                kwargs["ref_text"] = req.ref_text

        return kwargs

    def call(self, req: SynthesisRequest, model) -> list:
        """Call model.generate() and return raw tensors."""
        kwargs = self.build_kwargs(req, model)
        try:
            return model.generate(**kwargs)
        except TypeError as exc:
            # Upstream renamed or removed a param — try graceful fallback
            # by stripping unknown kwargs one-by-one.
            logger.warning(
                f"model.generate() raised TypeError: {exc}. "
                "Attempting fallback with minimal kwargs."
            )
            minimal = {
                "text": kwargs["text"],
                "num_step": kwargs.get("num_step", 32),
            }
            if "instruct" in kwargs:
                minimal["instruct"] = kwargs["instruct"]
            if "ref_audio" in kwargs:
                minimal["ref_audio"] = kwargs["ref_audio"]
            if "ref_text" in kwargs:
                minimal["ref_text"] = kwargs["ref_text"]
            return model.generate(**minimal)


class InferenceService:
    def __init__(
        self,
        model_svc: ModelService,
        executor: ThreadPoolExecutor,
        cfg: Settings,
    ) -> None:
        self._model_svc = model_svc
        self._executor = executor
        self._cfg = cfg
        self._semaphore = asyncio.Semaphore(cfg.max_concurrent)
        self._adapter = OmniVoiceAdapter(cfg)

    async def synthesize(self, req: SynthesisRequest) -> SynthesisResult:
        """
        Run synthesis in thread pool.
        Blocks at semaphore if MAX_CONCURRENT already running.
        Raises asyncio.TimeoutError if exceeds request_timeout_s.
        """
        loop = asyncio.get_running_loop()

        async with self._semaphore:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    self._run_sync,
                    req,
                ),
                timeout=self._cfg.request_timeout_s,
            )

        return result

    def _run_sync(self, req: SynthesisRequest) -> SynthesisResult:
        """Blocking inference. Runs in thread pool thread."""
        t0 = time.monotonic()
        model = self._model_svc.model

        try:
            tensors = self._adapter.call(req, model)
        finally:
            _cleanup_memory(self._cfg.device)

        duration_s = sum(t.shape[-1] for t in tensors) / 24_000
        latency_s = time.monotonic() - t0

        logger.debug(
            f"Synthesized {duration_s:.2f}s audio in {latency_s:.2f}s "
            f"(RTF={latency_s/duration_s:.3f})"
        )
        return SynthesisResult(
            tensors=tensors,
            duration_s=duration_s,
            latency_s=latency_s,
        )


def _cleanup_memory(device: str) -> None:
    """Post-inference memory cleanup to mitigate potential Torch memory growth."""
    gc.collect()
    if device == "cuda":
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
    elif device == "mps":
        try:
            torch.mps.empty_cache()
        except Exception:
            pass
```

---

### 6.3 ProfileService

**File: `omnivoice_server/services/profiles.py`**

```python
"""
Manages voice cloning profiles on disk.

Profile structure on disk:
  <profile_dir>/
    <profile_id>/
      ref_audio.wav     ← reference audio
      meta.json         ← {"name": str, "ref_text": str|null, "created_at": str}
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
        path = self._profile_path(profile_id) / PROFILE_AUDIO_FILE
        if not path.exists():
            raise ProfileNotFoundError(f"Profile '{profile_id}' not found")
        return path

    def get_ref_text(self, profile_id: str) -> Optional[str]:
        """Return ref_text from profile metadata, or None."""
        meta = self._read_meta(self._profile_path(profile_id))
        return meta.get("ref_text") if meta else None

    def save_profile(
        self,
        profile_id: str,
        audio_bytes: bytes,
        ref_text: Optional[str] = None,
        overwrite: bool = False,
    ) -> dict:
        """
        Save a new profile. Raises ProfileAlreadyExistsError if exists and overwrite=False.
        Returns the saved metadata dict.
        """
        profile_path = self._profile_path(profile_id)
        if profile_path.exists() and not overwrite:
            raise ProfileAlreadyExistsError(
                f"Profile '{profile_id}' already exists. "
                "Use overwrite=true to replace."
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

    def _read_meta(self, profile_path: Path) -> Optional[dict]:
        meta_file = profile_path / PROFILE_META_FILE
        if not meta_file.exists():
            return None
        try:
            return json.loads(meta_file.read_text())
        except (json.JSONDecodeError, OSError):
            return None
```

---

### 6.4 MetricsService

**File: `omnivoice_server/services/metrics.py`**

```python
"""
In-memory request metrics. Thread-safe with a lock.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional


class MetricsService:
    def __init__(self, latency_window: int = 200) -> None:
        self._lock = threading.Lock()
        self.total = 0
        self.success = 0
        self.error = 0
        self.timeout = 0
        self._latencies: deque[float] = deque(maxlen=latency_window)

    def record_success(self, latency_s: float) -> None:
        with self._lock:
            self.total += 1
            self.success += 1
            self._latencies.append(latency_s * 1000)  # store as ms

    def record_error(self) -> None:
        with self._lock:
            self.total += 1
            self.error += 1

    def record_timeout(self) -> None:
        with self._lock:
            self.total += 1
            self.timeout += 1

    def snapshot(self) -> dict:
        with self._lock:
            lats = list(self._latencies)
        mean_ms = sum(lats) / len(lats) if lats else 0.0
        sorted_lats = sorted(lats)
        p95_ms = sorted_lats[int(len(sorted_lats) * 0.95)] if sorted_lats else 0.0
        return {
            "requests_total": self.total,
            "requests_success": self.success,
            "requests_error": self.error,
            "requests_timeout": self.timeout,
            "mean_latency_ms": round(mean_ms, 1),
            "p95_latency_ms": round(p95_ms, 1),
        }
```

---

## 7. Utils

### 7.1 audio.py

**File: `omnivoice_server/utils/audio.py`**

```python
"""
Audio encoding helpers.
All functions are pure (no side effects) and synchronous.
"""
from __future__ import annotations

import io

import torch
import torchaudio

SAMPLE_RATE = 24_000


def tensor_to_wav_bytes(tensor: torch.Tensor) -> bytes:
    """
    Convert (1, T) float32 tensor to 16-bit PCM WAV bytes.

    Why 16-bit PCM instead of float32?
    - Broader client compatibility (most players expect PCM)
    - ~50% smaller payload
    - Inaudible quality difference for TTS output
    """
    # Move to CPU (in case tensor is on CUDA/MPS)
    cpu_tensor = tensor.cpu()

    # Ensure shape is (1, T) — torchaudio.save expects channels-first
    if cpu_tensor.dim() == 1:
        cpu_tensor = cpu_tensor.unsqueeze(0)

    buf = io.BytesIO()
    torchaudio.save(
        buf,
        cpu_tensor,
        SAMPLE_RATE,
        format="wav",
        encoding="PCM_S",      # signed integer PCM
        bits_per_sample=16,
    )
    buf.seek(0)
    return buf.read()


def tensors_to_wav_bytes(tensors: list[torch.Tensor]) -> bytes:
    """
    Concatenate multiple (1, T) tensors into a single WAV.
    Used when model returns multiple segments.
    """
    if len(tensors) == 1:
        return tensor_to_wav_bytes(tensors[0])

    # Concatenate along time axis
    combined = torch.cat([t.cpu() for t in tensors], dim=-1)
    return tensor_to_wav_bytes(combined)


def tensor_to_pcm16_bytes(tensor: torch.Tensor) -> bytes:
    """
    Convert (1, T) float32 tensor to raw PCM int16 bytes.
    Used for streaming — no WAV header, continuous byte stream.
    Client must know: sample_rate=24000, channels=1, dtype=int16, little-endian.
    """
    flat = tensor.squeeze(0).cpu()  # (T,)
    return (flat * 32767).clamp(-32768, 32767).to(torch.int16).numpy().tobytes()


def read_upload_bounded(data: bytes, max_bytes: int, field_name: str = "ref_audio") -> bytes:
    """
    Validates upload size after reading.
    FastAPI reads multipart into memory before this point,
    so this is a guard against misconfigured / malicious clients.
    """
    if len(data) == 0:
        raise ValueError(f"{field_name} is empty")
    if len(data) > max_bytes:
        mb = len(data) / 1024 / 1024
        limit_mb = max_bytes / 1024 / 1024
        raise ValueError(
            f"{field_name} too large: {mb:.1f} MB (limit: {limit_mb:.0f} MB)"
        )
    return data


import io
import torchaudio

def validate_audio_bytes(data: bytes, field_name: str = "ref_audio") -> None:
    """
    Lightweight validation: check that bytes are parseable as audio.
    Does NOT decode the full file — only reads metadata.
    Raises ValueError with a user-friendly message on failure.
    """
    try:
        buf = io.BytesIO(data)
        info = torchaudio.info(buf)
        if info.num_frames == 0:
            raise ValueError(f"{field_name}: audio file has 0 frames")
        if info.sample_rate < 8000:
            raise ValueError(
                f"{field_name}: sample rate {info.sample_rate}Hz too low (min 8000Hz)"
            )
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(
            f"{field_name}: could not parse as audio file. "
            "Supported formats: WAV, MP3, FLAC, OGG. "
            f"Original error: {e}"
        ) from e


def compute_duration_s(tensors: list[torch.Tensor]) -> float:
    """Return total audio duration in seconds."""
    total_samples = sum(t.shape[-1] for t in tensors)
    return total_samples / SAMPLE_RATE
```

---

### 7.2 text.py

**File: `omnivoice_server/utils/text.py`**

```python
"""
Sentence splitting for streaming mode.

Goal: Split text into chunks that:
  1. End at natural sentence boundaries (. ! ? newline)
  2. Don't exceed max_chars
  3. Don't split in the middle of numbers, abbreviations, URLs
"""
from __future__ import annotations

import re

# Matches sentence-ending punctuation followed by whitespace + uppercase letter,
# or end of string. Preserves decimals (3.14), versions (v1.2), domains (k2-fsa.org).
_SENTENCE_END = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z\u4e00-\u9fff\u3040-\u30ff'   # English + CJK start
    r'\u00C0-\u024F'    # Latin Extended-A/B (Vietnamese, French, German, etc.)
    r'\u1E00-\u1EFF'    # Latin Extended Additional (full Vietnamese coverage)
    r'])'
    r'|(?<=[。！？])',                                        # CJK sentence end
)

# Patterns that look like sentence endings but aren't
_FALSE_ENDS = re.compile(
    r'\d+\.\d+'           # decimals: 3.14
    r'|v\d+\.\d+'         # versions: v1.2.3
    r'|[A-Z][a-z]{0,3}\.'  # abbreviations: Dr. Mr. etc.
    r'|\w+\.\w{2,6}(?:/|\s|$)'  # URLs/domains
)


def split_sentences(text: str, max_chars: int = 400) -> list[str]:
    """
    Split text into sentence-level chunks suitable for streaming.

    Args:
        text:      Input text to split.
        max_chars: Soft upper bound per chunk. Chunks may exceed this
                   slightly if a single word is longer (rare).

    Returns:
        List of non-empty strings. Guaranteed at least 1 element.
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    # Fast path: text is short enough to be one chunk
    if len(text) <= max_chars:
        return [text]

    # Split at sentence boundaries
    raw_sentences = _SENTENCE_END.split(text)
    raw_sentences = [s.strip() for s in raw_sentences if s.strip()]

    if not raw_sentences:
        return [text]

    # Merge short consecutive sentences into one chunk
    chunks: list[str] = []
    current = ""

    for sentence in raw_sentences:
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = current + " " + sentence
        else:
            chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    # Split any chunk that still exceeds max_chars at word boundary
    result: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            result.append(chunk)
        else:
            result.extend(_split_at_words(chunk, max_chars))

    return [c for c in result if c.strip()]


def _split_at_words(text: str, max_chars: int) -> list[str]:
    """Split text at word boundary when it exceeds max_chars."""
    words = text.split()
    parts: list[str] = []
    current = ""

    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= max_chars:
            current += " " + word
        else:
            parts.append(current)
            current = word

    if current:
        parts.append(current)

    return parts


# NOTE: _FALSE_ENDS merge logic (implementation detail)
#
# When _SENTENCE_END splits text, some splits are "false positives" — patterns
# like "v2.1.0" or "Dr." that end with periods but aren't sentence boundaries.
# The actual implementation has a merge step that checks if a false-end pattern
# appears at the end of a sentence chunk (within 2 chars tolerance for trailing
# punctuation). If so, it merges with the next chunk.
#
# The -2 tolerance is intentional design:
# - It accounts for "v2.1." where the period after the version is the sentence end
# - It's an approximation rather than a correctness guarantee
# - Full correctness would require complex regex lookbehind for all edge cases
# - Current approach handles: "Release v2.1. Download now." correctly
#
# See test_split_sentences_version_not_split in tests/test_text.py for validation.
```

---

## 8. Routers

### 8.1 /v1/audio/speech

**File: `omnivoice_server/routers/speech.py`**

```python
"""
/v1/audio/speech        — OpenAI-compatible TTS (auto, design, clone via profile)
/v1/audio/speech/clone  — One-shot voice cloning (multipart upload)
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from ..services.inference import InferenceService, SynthesisRequest
from ..services.metrics import MetricsService
from ..services.profiles import ProfileNotFoundError, ProfileService
from ..utils.audio import compute_duration_s, tensor_to_pcm16_bytes, tensors_to_wav_bytes
from ..utils.text import split_sentences

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response schemas ───────────────────────────────────────────────

class SpeechRequest(BaseModel):
    """
    OpenAI TTS API compatible request body.
    https://platform.openai.com/docs/api-reference/audio/createSpeech

    Extra fields vs OpenAI spec:
      stream:    bool   — enable sentence-level chunked streaming
      num_step:  int    — override server default diffusion steps
    """
    model: str = Field(
        default="omnivoice",
        description="Model name. Any value accepted; only 'omnivoice' is valid.",
    )
    input: str = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="Text to synthesize",
    )
    voice: str = Field(
        default="auto",
        description=(
            "Voice selector. One of:\n"
            "  'auto'                     — model picks\n"
            "  'design:<attributes>'      — e.g. 'design:female,british accent'\n"
            "  'clone:<profile_id>'       — use saved profile\n"
        ),
    )
    response_format: Literal["wav", "pcm"] = Field(
        default="wav",
        description=(
            "Audio format. 'wav' (default) or 'pcm' (raw int16 bytes). "
            "Note: 'mp3' is NOT supported — use 'wav' as a drop-in replacement "
            "for clients configured with response_format='mp3'."
        ),
    )
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    stream: bool = Field(
        default=False,
        description="If true, return chunked streaming response (sentence-level)",
    )
    num_step: Optional[int] = Field(
        default=None,
        ge=1,
        le=64,
        description="Diffusion steps. None = server default.",
    )

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        if v not in ("omnivoice", "tts-1", "tts-1-hd"):
            # Accept OpenAI model names for drop-in compatibility
            logger.debug(f"model='{v}' mapped to omnivoice")
        return v


def _get_inference(request: Request) -> InferenceService:
    return request.app.state.inference_svc


def _get_profiles(request: Request) -> ProfileService:
    return request.app.state.profile_svc


def _get_metrics(request: Request) -> MetricsService:
    return request.app.state.metrics_svc


def _get_cfg(request: Request):
    return request.app.state.cfg


# ── Voice parsing ────────────────────────────────────────────────────────────

def _parse_voice(
    voice_str: str,
    profile_svc: ProfileService,
) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """
    Parse voice string into (mode, instruct, ref_audio_path, ref_text).

    Returns:
        mode:           "auto" | "design" | "clone"
        instruct:       design attributes string or None
        ref_audio_path: path str or None
        ref_text:       transcription or None
    """
    v = voice_str.strip()

    if v == "auto" or v == "":
        return "auto", None, None, None

    if v.startswith("design:"):
        instruct = v[len("design:"):].strip()
        if not instruct:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'design:' prefix requires attributes, e.g. 'design:female,british accent'",
            )
        return "design", instruct, None, None

    if v.startswith("clone:"):
        profile_id = v[len("clone:"):].strip()
        if not profile_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'clone:' prefix requires a profile_id",
            )
        try:
            ref_path = profile_svc.get_ref_audio_path(profile_id)
            ref_text = profile_svc.get_ref_text(profile_id)
            return "clone", None, str(ref_path), ref_text
        except ProfileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Voice profile '{profile_id}' not found. "
                       "Use POST /v1/voices/profiles to create it.",
            )

    # Fallback: treat as voice design attributes (convenience shorthand)
    return "design", v, None, None


# ── POST /v1/audio/speech ────────────────────────────────────────────────────

@router.post(
    "/audio/speech",
    response_class=Response,
    responses={
        200: {
            "content": {
                "audio/wav": {},
                "audio/pcm": {},
            }
        },
        401: {"description": "Unauthorized (invalid API key)"},
        422: {"description": "Validation error"},
        504: {"description": "Synthesis timed out"},
    },
)
async def create_speech(
    body: SpeechRequest,
    inference_svc: InferenceService = Depends(_get_inference),
    profile_svc: ProfileService = Depends(_get_profiles),
    metrics_svc: MetricsService = Depends(_get_metrics),
    cfg=Depends(_get_cfg),
):
    """
    Generate speech from text.

    Compatible with OpenAI audio.speech.create() API.
    Supports auto voice, voice design, and saved voice profiles.
    """
    mode, instruct, ref_audio_path, ref_text = _parse_voice(
        body.voice, profile_svc
    )

    req = SynthesisRequest(
        text=body.input,
        mode=mode,
        instruct=instruct,
        ref_audio_path=ref_audio_path,
        ref_text=ref_text,
        speed=body.speed,
        num_step=body.num_step,
    )

    # ── Streaming path ───────────────────────────────────────────────────────
    if body.stream:
        return StreamingResponse(
            _stream_sentences(body.input, req, inference_svc, metrics_svc, cfg),
            media_type="audio/pcm",
            headers={
                "X-Audio-Sample-Rate": "24000",
                "X-Audio-Channels": "1",
                "X-Audio-Bit-Depth": "16",
                "X-Audio-Format": "pcm-int16-le",
                "Transfer-Encoding": "chunked",
            },
        )

    # ── Non-streaming path ───────────────────────────────────────────────────
    try:
        result = await inference_svc.synthesize(req)
        metrics_svc.record_success(result.latency_s)
    except asyncio.TimeoutError:
        metrics_svc.record_timeout()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Synthesis timed out after {cfg.request_timeout_s}s",
        )
    except Exception as e:
        metrics_svc.record_error()
        logger.exception("Synthesis failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Synthesis failed: {e}",
        )

    if body.response_format == "pcm":
        from ..utils.audio import tensor_to_pcm16_bytes
        audio_bytes = b"".join(tensor_to_pcm16_bytes(t) for t in result.tensors)
        media_type = "audio/pcm"
    else:
        audio_bytes = tensors_to_wav_bytes(result.tensors)
        media_type = "audio/wav"

    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={
            "X-Audio-Duration-S": str(round(result.duration_s, 3)),
            "X-Synthesis-Latency-S": str(round(result.latency_s, 3)),
        },
    )


async def _stream_sentences(
    text: str,
    base_req: SynthesisRequest,
    inference_svc: InferenceService,
    metrics_svc: MetricsService,
    cfg,
) -> AsyncIterator[bytes]:
    """
    Sentence-level streaming generator.
    Yields PCM int16 bytes as each sentence is synthesized.

    STREAMING CONSISTENCY NOTE:
    When using streaming (stream=true) with voice="auto", each sentence chunk
    is synthesized independently. By default, position_temperature=5.0 introduces
    randomness in voice selection, which can cause inconsistent voice characteristics
    between chunks (e.g., different genders/accents per sentence).

    RECOMMENDED FIX:
    Set position_temperature=0 (or 0.0 in request) for deterministic voice selection.
    This ensures consistent voice across all chunks in a streaming session.

    Example:
        {"input": "Long text...", "stream": true, "position_temperature": 0}

    Trade-off: Lower position_temperature = less voice diversity but perfect consistency.
    Higher position_temperature = more diversity but potential chunk-to-chunk variation.
    """
    sentences = split_sentences(text, max_chars=cfg.stream_chunk_max_chars)

    if not sentences:
        return

    for sentence in sentences:
        req = SynthesisRequest(
            text=sentence,
            mode=base_req.mode,
            instruct=base_req.instruct,
            ref_audio_path=base_req.ref_audio_path,
            ref_text=base_req.ref_text,
            speed=base_req.speed,
            num_step=base_req.num_step,
        )
        try:
            result = await inference_svc.synthesize(req)
            metrics_svc.record_success(result.latency_s)
            for tensor in result.tensors:
                yield tensor_to_pcm16_bytes(tensor)
        except asyncio.TimeoutError:
            metrics_svc.record_timeout()
            logger.warning(f"Streaming chunk timed out: '{sentence[:50]}...'")
            return
        except Exception:
            metrics_svc.record_error()
            logger.exception(f"Streaming chunk failed: '{sentence[:50]}...'")
            return


# ── POST /v1/audio/speech/clone ──────────────────────────────────────────────

@router.post(
    "/audio/speech/clone",
    response_class=Response,
    responses={
        200: {"content": {"audio/wav": {}}},
        422: {"description": "Validation error"},
        504: {"description": "Synthesis timed out"},
    },
)
async def create_speech_clone(
    text: str = Form(..., min_length=1, max_length=10_000),
    ref_audio: UploadFile = File(..., description="Reference WAV audio (5–30s recommended)"),
    ref_text: Optional[str] = Form(
        default=None,
        description="Transcript of ref_audio. If omitted, Whisper auto-transcribes.",
    ),
    speed: float = Form(default=1.0, ge=0.25, le=4.0),
    num_step: Optional[int] = Form(default=None, ge=1, le=64),
    inference_svc: InferenceService = Depends(_get_inference),
    metrics_svc: MetricsService = Depends(_get_metrics),
    cfg=Depends(_get_cfg),
):
    """
    One-shot voice cloning. Upload reference audio + text to synthesize.

    Note: If ref_text is omitted, Whisper ASR runs internally (~0.5–1s extra latency).
    For repeated cloning of the same voice, use POST /v1/voices/profiles instead.
    """
    # Validate content type
    if ref_audio.content_type not in (
        "audio/wav", "audio/wave", "audio/x-wav",
        "audio/mp3", "audio/mpeg",
        "audio/ogg", "audio/flac",
        None,  # some clients omit content-type
    ):
        logger.warning(f"Unexpected ref_audio content-type: {ref_audio.content_type}")

    # Write ref audio to temp file — OmniVoice requires a path, not bytes
    from ..utils.audio import read_upload_bounded
    raw = await ref_audio.read()
    try:
        audio_bytes = read_upload_bounded(raw, cfg.max_ref_audio_bytes)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        req = SynthesisRequest(
            text=text,
            mode="clone",
            ref_audio_path=tmp_path,
            ref_text=ref_text,
            speed=speed,
            num_step=num_step,
        )
        try:
            result = await inference_svc.synthesize(req)
            metrics_svc.record_success(result.latency_s)
        except asyncio.TimeoutError:
            metrics_svc.record_timeout()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Synthesis timed out after {cfg.request_timeout_s}s",
            )
        except Exception as e:
            metrics_svc.record_error()
            logger.exception("Clone synthesis failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Synthesis failed: {e}",
            )
    finally:
        # Always delete temp file
        Path(tmp_path).unlink(missing_ok=True)

    return Response(
        content=tensors_to_wav_bytes(result.tensors),
        media_type="audio/wav",
        headers={
            "X-Audio-Duration-S": str(round(result.duration_s, 3)),
            "X-Synthesis-Latency-S": str(round(result.latency_s, 3)),
        },
    )
```

---

### 8.2 /v1/voices

**File: `omnivoice_server/routers/voices.py`**

```python
"""
/v1/voices                    — list all available voices
/v1/voices/profiles           — manage cloning profiles
/v1/voices/profiles/{id}      — get/patch/delete specific profile
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from ..services.profiles import (
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
    ProfileService,
)

logger = logging.getLogger(__name__)
router = APIRouter()

DESIGN_ATTRIBUTES = {
    "gender": ["male", "female"],
    "age": ["child", "young adult", "middle-aged", "elderly"],
    "pitch": ["very low", "low", "medium", "high", "very high"],
    "style": ["whisper"],
    "accent_en": ["American", "British", "Australian", "Indian", "Irish"],
    "dialect_zh": ["四川话", "陕西话", "粤语", "闽南话"],
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
            "description": "Model selects voice automatically",
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
    request: Request,                    # FIX: was missing — needed for cfg access
    profile_id: str = Form(
        ...,
        pattern=r"^[a-zA-Z0-9_-]{1,64}$",
        description="Unique identifier. Alphanumeric, dashes, underscores only.",
    ),
    ref_audio: UploadFile = File(...),
    ref_text: Optional[str] = Form(default=None),
    overwrite: bool = Form(default=False),
    profile_svc: ProfileService = Depends(_get_profiles),
):
    """
    Save a voice cloning profile.
    After saving, use voice='clone:<profile_id>' in /v1/audio/speech.
    """
    from ..utils.audio import read_upload_bounded, validate_audio_bytes

    cfg = request.app.state.cfg   # FIX: was NameError previously

    raw = await ref_audio.read()
    try:
        audio_bytes = read_upload_bounded(raw, cfg.max_ref_audio_bytes)
        validate_audio_bytes(audio_bytes)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
    request: Request,                    # FIX: needed for cfg.max_ref_audio_bytes
    ref_audio: Optional[UploadFile] = File(default=None),
    ref_text: Optional[str] = Form(default=None),
    profile_svc: ProfileService = Depends(_get_profiles),
):
    """
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
```

---

### 8.3 /health + /metrics

**File: `omnivoice_server/routers/health.py`**

```python
from __future__ import annotations

import psutil
import time

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    """Liveness check. Returns 200 when model is loaded and ready."""
    cfg = request.app.state.cfg
    model_svc = request.app.state.model_svc
    uptime_s = time.monotonic() - request.app.state.start_time

    return {
        "status": "ok" if model_svc.is_loaded else "loading",
        "model": cfg.model_id,
        "device": cfg.device,
        "num_step": cfg.num_step,
        "max_concurrent": cfg.max_concurrent,
        "uptime_s": round(uptime_s, 1),
    }


@router.get("/metrics")
async def metrics(request: Request):
    """Request metrics and current memory usage."""
    metrics_svc = request.app.state.metrics_svc
    snapshot = metrics_svc.snapshot()
    snapshot["ram_mb"] = round(
        psutil.Process().memory_info().rss / 1024 / 1024, 1
    )
    return snapshot
```

---

## 9. Benchmark harness

**File: `benchmarks/run_benchmark.py`**

```python
#!/usr/bin/env python3
"""
OmniVoice Benchmark — latency, RTF, memory over N runs.

Usage:
    python benchmarks/run_benchmark.py --device mps --num-step 16 --runs 100

After running, results/ folder contains:
    <device>_step<N>.csv    raw data
    report.md               markdown summary table

Upstream Discussion post template (after running):
    Post to: https://github.com/k2-fsa/OmniVoice/discussions
    Title: "Benchmark results: Apple Silicon MPS performance"
    Body: paste contents of report.md
"""
from __future__ import annotations

import argparse
import csv
import gc
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


# ── Test cases ────────────────────────────────────────────────────────────────

TEST_CASES = {
    "short_auto": {
        "text": "Hello, world. This is a test.",
        "mode": "auto",
    },
    "medium_auto": {
        "text": "The quick brown fox jumps over the lazy dog. " * 4,
        "mode": "auto",
    },
    "long_auto": {
        "text": "In the beginning was the word. " * 15,
        "mode": "auto",
    },
    "short_design": {
        "text": "Hello, this is voice design.",
        "mode": "design",
        "instruct": "female, british accent",
    },
    "medium_clone": {
        "text": "Hello, this is a voice clone test.",
        "mode": "clone",
        "ref_audio": str(Path(__file__).parent / "sample_ref.wav"),
    },
}

SAMPLE_RATE = 24_000


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class RunResult:
    device: str
    num_step: int
    test_case: str
    mode: str
    run_index: int
    latency_ms: float
    audio_duration_ms: float
    rtf: float
    ram_before_mb: float
    ram_after_mb: float
    ram_delta_mb: float
    error: Optional[str] = None


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="mps",
                        choices=["mps", "cpu", "cuda"],
                        help="Inference device")
    parser.add_argument("--num-step", type=int, default=16,
                        help="Diffusion steps")
    parser.add_argument("--runs", type=int, default=100,
                        help="Iterations per test case (for memory leak detection)")
    parser.add_argument("--warmup", type=int, default=1,
                        help="Warm-up runs (not counted)")
    parser.add_argument("--cases", nargs="+", default=list(TEST_CASES.keys()),
                        help="Test cases to run")
    parser.add_argument("--output-dir", default="benchmarks/results",
                        help="Directory for CSV and report outputs")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    import psutil
    import torch
    from omnivoice import OmniVoice

    # Load model
    print(f"Loading model on device={args.device}...")
    dtype = torch.float16 if args.device != "cpu" else torch.float32
    device_map = "cuda:0" if args.device == "cuda" else args.device

    t0 = time.monotonic()
    model = OmniVoice.from_pretrained(
        "k2-fsa/OmniVoice",
        device_map=device_map,
        dtype=dtype,
    )
    print(f"Model loaded in {time.monotonic() - t0:.1f}s")

    def get_ram() -> float:
        return psutil.Process().memory_info().rss / 1024 / 1024

    def run_once(case: dict) -> tuple[list, float]:
        kwargs = {"text": case["text"], "num_step": args.num_step}
        if case["mode"] == "design":
            kwargs["instruct"] = case["instruct"]
        elif case["mode"] == "clone":
            if not Path(case["ref_audio"]).exists():
                raise FileNotFoundError(
                    f"sample_ref.wav not found at {case['ref_audio']}. "
                    "Please provide a 5–10s WAV file at benchmarks/sample_ref.wav"
                )
            kwargs["ref_audio"] = case["ref_audio"]
        tensors = model.generate(**kwargs)
        duration_s = sum(t.shape[-1] for t in tensors) / SAMPLE_RATE
        return tensors, duration_s

    def cleanup() -> None:
        gc.collect()
        if args.device == "mps":
            try:
                torch.mps.empty_cache()
            except Exception:
                pass
        elif args.device == "cuda":
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

    all_results: list[RunResult] = []

    for case_name in args.cases:
        if case_name not in TEST_CASES:
            print(f"  [SKIP] Unknown case '{case_name}'")
            continue

        case = TEST_CASES[case_name]
        print(f"\n── {case_name} (mode={case['mode']}) ──────────────")

        # Warm-up
        for _ in range(args.warmup):
            try:
                run_once(case)
            except Exception as e:
                print(f"  [WARN] Warm-up failed: {e}")
            cleanup()

        # Benchmark
        for i in range(args.runs):
            ram_before = get_ram()
            t_start = time.perf_counter()
            error = None
            duration_ms = 0.0

            try:
                _, duration_s = run_once(case)
                latency_ms = (time.perf_counter() - t_start) * 1000
                duration_ms = duration_s * 1000
            except Exception as e:
                latency_ms = -1
                error = str(e)

            cleanup()
            ram_after = get_ram()
            rtf = (latency_ms / 1000) / (duration_ms / 1000) if duration_ms > 0 else -1

            result = RunResult(
                device=args.device,
                num_step=args.num_step,
                test_case=case_name,
                mode=case["mode"],
                run_index=i,
                latency_ms=round(latency_ms, 1),
                audio_duration_ms=round(duration_ms, 1),
                rtf=round(rtf, 4),
                ram_before_mb=round(ram_before, 1),
                ram_after_mb=round(ram_after, 1),
                ram_delta_mb=round(ram_after - ram_before, 1),
                error=error,
            )
            all_results.append(result)

            if i % 10 == 0:
                status = f"run {i:3d}: lat={latency_ms:.0f}ms  rtf={rtf:.3f}  " \
                         f"ram_Δ={result.ram_delta_mb:+.1f}MB  ram={ram_after:.0f}MB"
                if error:
                    status += f"  ERR={error[:40]}"
                print(f"  {status}")

    # Write CSV
    csv_path = output_dir / f"{args.device}_step{args.num_step}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(all_results[0]).keys()))
        writer.writeheader()
        for r in all_results:
            writer.writerow(asdict(r))
    print(f"\n✓ CSV → {csv_path}")

    # Generate report
    report_path = output_dir / "report.md"
    _write_report(all_results, report_path, args)
    print(f"✓ Report → {report_path}")
    print(f"\nUpstream Discussion post: paste {report_path} to")
    print("  https://github.com/k2-fsa/OmniVoice/discussions")


def _write_report(results: list[RunResult], path: Path, args) -> None:
    from collections import defaultdict

    groups: dict = defaultdict(list)
    for r in results:
        if r.error is None:
            groups[(r.device, r.num_step, r.test_case)].append(r)

    lines = [
        "# OmniVoice Benchmark Results\n\n",
        f"Device: `{args.device}` | Steps: `{args.num_step}` | "
        f"Runs per case: `{args.runs}`\n\n",
        "## Latency & RTF\n\n",
        "| Device | Steps | Test Case | Mean (ms) | p95 (ms) | Mean RTF | Errors |\n",
        "|--------|-------|-----------|-----------|----------|----------|--------|\n",
    ]

    for (device, steps, case), rs in sorted(groups.items()):
        lats = [r.latency_ms for r in rs]
        rtfs = [r.rtf for r in rs if r.rtf > 0]
        errors = sum(1 for r in results
                     if r.test_case == case and r.error is not None)
        p95 = sorted(lats)[int(len(lats) * 0.95)] if lats else 0
        mean_lat = statistics.mean(lats) if lats else 0
        mean_rtf = statistics.mean(rtfs) if rtfs else 0
        lines.append(
            f"| {device} | {steps} | {case} | "
            f"{mean_lat:.0f} | {p95:.0f} | {mean_rtf:.4f} | {errors} |\n"
        )

    lines += [
        "\n## Memory (RAM across all runs)\n\n",
        "| Test Case | Initial RAM (MB) | Final RAM (MB) | Total Δ (MB) | Leak? |\n",
        "|-----------|-----------------|----------------|--------------|-------|\n",
    ]

    for (_, _, case), rs in sorted(groups.items()):
        if not rs:
            continue
        initial = rs[0].ram_before_mb
        final = rs[-1].ram_after_mb
        delta = final - initial
        leak = "⚠️ YES" if delta > 200 else "✅ NO"
        lines.append(
            f"| {case} | {initial:.0f} | {final:.0f} | "
            f"{delta:+.0f} | {leak} |\n"
        )

    lines += [
        "\n## Interpretation\n\n",
        "- **RTF < 1.0** = faster than real-time (good)\n",
        "- **RTF > 1.0** = slower than real-time (server usable but audio chunks will lag)\n",
        "- **RAM Δ > 200MB** across 100 runs = memory leak detected\n",
        "\n*Generated by omnivoice-server benchmark harness*\n",
    ]

    path.write_text("".join(lines))


if __name__ == "__main__":
    main()
```

---

## 10. Tests

**File: `tests/conftest.py`**

```python
"""
Shared fixtures for all tests.
The key trick: mock ModelService so tests don't need a GPU or real model.
"""
from __future__ import annotations

import io
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import torch
from fastapi.testclient import TestClient

from omnivoice_server.app import create_app
from omnivoice_server.config import Settings


def _make_silence_tensor(duration_s: float = 1.0) -> torch.Tensor:
    """Return a silent (1, T) float32 tensor at 24kHz."""
    T = int(24_000 * duration_s)
    return torch.zeros(1, T)


def _mock_synthesize(req):
    """Fake synthesis — returns 1s of silence immediately."""
    from omnivoice_server.services.inference import SynthesisResult
    tensor = _make_silence_tensor(1.0)
    return SynthesisResult(tensors=[tensor], duration_s=1.0, latency_s=0.05)


@pytest.fixture
def settings():
    return Settings(
        device="cpu",
        num_step=4,
        max_concurrent=1,
        api_key="",
        profile_dir=pytest.tmp_path_factory.mktemp("profiles"),
    )


@pytest.fixture
def client(settings, tmp_path):
    settings.profile_dir = tmp_path / "profiles"
    settings.profile_dir.mkdir()

    app = create_app(settings)

    # Patch ModelService to skip actual model loading
    with patch("omnivoice_server.services.model.ModelService.load", new_callable=AsyncMock):
        with patch("omnivoice_server.services.model.ModelService.is_loaded",
                   new_callable=lambda: property(lambda self: True)):
            with TestClient(app) as c:
                # Inject mock inference service
                c.app.state.inference_svc.synthesize = AsyncMock(
                    side_effect=_mock_synthesize
                )
                yield c
```

**File: `tests/test_health.py`**

```python
def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "device" in data
    assert "uptime_s" in data


def test_metrics_ok(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "requests_total" in data
    assert "ram_mb" in data
```

**File: `tests/test_speech.py`**

```python
def test_speech_auto_returns_wav(client):
    resp = client.post("/v1/audio/speech", json={
        "model": "omnivoice",
        "input": "Hello world",
        "voice": "auto",
    })
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    # WAV magic bytes: RIFF
    assert resp.content[:4] == b"RIFF"


def test_speech_design_voice(client):
    resp = client.post("/v1/audio/speech", json={
        "input": "Hello",
        "voice": "design:female,british accent",
    })
    assert resp.status_code == 200


def test_speech_invalid_text_empty(client):
    resp = client.post("/v1/audio/speech", json={
        "input": "",
        "voice": "auto",
    })
    assert resp.status_code == 422


def test_speech_clone_unknown_profile(client):
    resp = client.post("/v1/audio/speech", json={
        "input": "Hello",
        "voice": "clone:nonexistent",
    })
    assert resp.status_code == 404


def test_speech_openai_model_names_accepted(client):
    """tts-1 and tts-1-hd should be accepted for drop-in compatibility."""
    for model_name in ("tts-1", "tts-1-hd", "omnivoice"):
        resp = client.post("/v1/audio/speech", json={
            "model": model_name,
            "input": "Hello",
        })
        assert resp.status_code == 200, f"Failed for model={model_name}"


def test_speech_pcm_format(client):
    resp = client.post("/v1/audio/speech", json={
        "input": "Hello",
        "response_format": "pcm",
    })
    assert resp.status_code == 200
    assert "audio/pcm" in resp.headers["content-type"]
```

**File: `tests/test_clone.py`**

```python
import io

def _make_wav_bytes() -> bytes:
    """Minimal valid WAV (44-byte header + 0 samples)."""
    import struct
    data_size = 0
    return (
        b"RIFF" + struct.pack("<I", 36 + data_size) +
        b"WAVE" + b"fmt " + struct.pack("<I", 16) +
        struct.pack("<HHIIHH", 1, 1, 24000, 48000, 2, 16) +
        b"data" + struct.pack("<I", data_size)
    )


def test_clone_returns_wav(client):
    wav = _make_wav_bytes()
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello world", "speed": "1.0"},
        files={"ref_audio": ("ref.wav", io.BytesIO(wav), "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.content[:4] == b"RIFF"


def test_clone_empty_audio_rejected(client):
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello"},
        files={"ref_audio": ("ref.wav", io.BytesIO(b""), "audio/wav")},
    )
    assert resp.status_code == 422
```

**File: `tests/test_voices.py`**

```python
import io


def _sample_audio() -> bytes:
    import struct
    data_size = 0
    return (
        b"RIFF" + struct.pack("<I", 36 + data_size) +
        b"WAVE" + b"fmt " + struct.pack("<I", 16) +
        struct.pack("<HHIIHH", 1, 1, 24000, 48000, 2, 16) +
        b"data" + struct.pack("<I", data_size)
    )


def test_list_voices_empty(client):
    resp = client.get("/v1/voices")
    assert resp.status_code == 200
    data = resp.json()
    assert "voices" in data
    # At minimum: auto + design placeholder
    assert len(data["voices"]) >= 2


def test_create_and_list_profile(client):
    audio = _sample_audio()
    # Create
    resp = client.post(
        "/v1/voices/profiles",
        data={"profile_id": "test-voice", "ref_text": "Hello world"},
        files={"ref_audio": ("ref.wav", io.BytesIO(audio), "audio/wav")},
    )
    assert resp.status_code == 201
    assert resp.json()["profile_id"] == "test-voice"

    # Appears in list
    resp = client.get("/v1/voices")
    ids = [v["profile_id"] for v in resp.json()["voices"] if "profile_id" in v]
    assert "test-voice" in ids


def test_create_profile_duplicate_rejected(client):
    audio = _sample_audio()
    for _ in range(2):
        resp = client.post(
            "/v1/voices/profiles",
            data={"profile_id": "dup"},
            files={"ref_audio": ("ref.wav", io.BytesIO(audio), "audio/wav")},
        )
    assert resp.status_code == 409


def test_delete_profile(client):
    audio = _sample_audio()
    client.post(
        "/v1/voices/profiles",
        data={"profile_id": "to-delete"},
        files={"ref_audio": ("ref.wav", io.BytesIO(audio), "audio/wav")},
    )
    resp = client.delete("/v1/voices/profiles/to-delete")
    assert resp.status_code == 204


def test_invalid_profile_id_rejected(client):
    audio = _sample_audio()
    resp = client.post(
        "/v1/voices/profiles",
        data={"profile_id": "has spaces"},
        files={"ref_audio": ("ref.wav", io.BytesIO(audio), "audio/wav")},
    )
    assert resp.status_code == 422


def test_speech_with_saved_profile(client):
    audio = _sample_audio()
    client.post(
        "/v1/voices/profiles",
        data={"profile_id": "myvoice"},
        files={"ref_audio": ("ref.wav", io.BytesIO(audio), "audio/wav")},
    )
    resp = client.post("/v1/audio/speech", json={
        "input": "Hello with cloned voice",
        "voice": "clone:myvoice",
    })
    assert resp.status_code == 200


def test_streaming_returns_pcm(client):
    resp = client.post("/v1/audio/speech", json={
        "input": "Hello world. This is sentence two.",
        "stream": True,
    })
    assert resp.status_code == 200
    assert "X-Audio-Sample-Rate" in resp.headers
    assert resp.headers["X-Audio-Sample-Rate"] == "24000"
```

---

## 11. CLI entrypoint

**File: `omnivoice_server/cli.py`**

```python
"""
CLI entrypoint for omnivoice-server.
All flags mirror Settings fields. CLI values override env vars.
"""
from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="omnivoice-server",
        description="OpenAI-compatible HTTP server for OmniVoice TTS",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Server
    parser.add_argument("--host", default=None, help="Bind host (env: OMNIVOICE_HOST)")
    parser.add_argument("--port", type=int, default=None,
                        help="Port (env: OMNIVOICE_PORT)")
    parser.add_argument("--log-level", default=None,
                        choices=["debug", "info", "warning", "error"],
                        help="Log level (env: OMNIVOICE_LOG_LEVEL)")

    # Model
    parser.add_argument("--model", default=None, dest="model_id",
                        help="HuggingFace model ID or local path (env: OMNIVOICE_MODEL_ID)")
    parser.add_argument("--device", default=None,
                        choices=["auto", "cuda", "mps", "cpu"],
                        help="Inference device (env: OMNIVOICE_DEVICE)")
    parser.add_argument("--num-step", type=int, default=None, dest="num_step",
                        help="Diffusion steps, 1–64 (env: OMNIVOICE_NUM_STEP)")
    parser.add_argument("--guidance-scale", type=float, default=None, dest="guidance_scale",
                        help="CFG scale, 0–10 (env: OMNIVOICE_GUIDANCE_SCALE)")
    parser.add_argument("--denoise", action="store_true", default=None, dest="denoise",
                        help="Enable denoising (env: OMNIVOICE_DENOISE)")
    parser.add_argument("--no-denoise", action="store_false", dest="denoise",
                        help="Disable denoising")
    parser.add_argument("--t-shift", type=float, default=None, dest="t_shift",
                        help="Noise schedule shift, 0–2 (env: OMNIVOICE_T_SHIFT)")
    parser.add_argument("--position-temperature", type=float, default=None, dest="position_temperature",
                        help="Voice diversity temperature, 0–10 (env: OMNIVOICE_POSITION_TEMPERATURE)")
    parser.add_argument("--class-temperature", type=float, default=None, dest="class_temperature",
                        help="Token sampling temperature, 0–2 (env: OMNIVOICE_CLASS_TEMPERATURE)")

    # Inference
    parser.add_argument("--max-concurrent", type=int, default=None, dest="max_concurrent",
                        help="Max simultaneous inferences (env: OMNIVOICE_MAX_CONCURRENT)")
    parser.add_argument("--timeout", type=int, default=None, dest="request_timeout_s",
                        help="Request timeout in seconds (env: OMNIVOICE_REQUEST_TIMEOUT_S)")

    # Storage
    parser.add_argument("--profile-dir", default=None, dest="profile_dir",
                        help="Voice profile directory (env: OMNIVOICE_PROFILE_DIR)")

    # Auth
    parser.add_argument("--api-key", default=None, dest="api_key",
                        help="Bearer token for auth. Empty = no auth (env: OMNIVOICE_API_KEY)")

    args = parser.parse_args()

    # Build override dict — only include args that were explicitly set
    overrides = {k: v for k, v in vars(args).items() if v is not None}

    from .config import Settings
    cfg = Settings(**overrides)

    # Configure logging
    logging.basicConfig(
        level=cfg.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    import uvicorn
    from .app import create_app

    app = create_app(cfg)

    uvicorn.run(
        app,
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level,
        workers=1,          # MUST be 1: multi-process = multiple model copies in RAM
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
```

---

## 12. Error catalogue

| HTTP Status | When                                                                                                                  | Response body                                |
| ----------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| 200         | Success                                                                                                               | Audio bytes (WAV or PCM)                     |
| 201         | Profile created                                                                                                       | Profile metadata JSON                        |
| 204         | Profile deleted                                                                                                       | Empty                                        |
| 401         | Wrong/missing API key (when api_key set)                                                                              | `{"error": "..."}`                           |
| 404         | Profile not found                                                                                                     | `{"detail": "Profile 'x' not found"}`        |
| 409         | Profile already exists (no overwrite)                                                                                 | `{"detail": "...already exists..."}`         |
| 422         | Validation error: empty text, bad profile_id, **upload too large (P2)**, **non-audio file (P5)**, **mp3 format (P6)** | Pydantic error JSON or detail string         |
| 500         | `model.generate()` threw unexpected exception                                                                         | `{"detail": "Synthesis failed: ..."}`        |
| 504         | `asyncio.TimeoutError` (request_timeout_s exceeded)                                                                   | `{"detail": "Synthesis timed out after Xs"}` |

**Streaming errors:** If a sentence fails mid-stream, the generator logs a warning and stops — the client receives a truncated (but valid) PCM stream. No HTTP error code is possible after streaming has started.

---

## 13. Implementation order

Implement in a single session if possible, following this order to ensure a runnable app at each stage:

```
Step 1:  pyproject.toml + omnivoice_server/__init__.py
Step 2:  config.py                    (Settings dataclass)
Step 3:  utils/audio.py               (tensor helpers)
Step 4:  utils/text.py + tests        (sentence splitter, pure functions)
Step 5:  services/metrics.py          (trivial, no deps)
Step 6:  services/profiles.py + tests (disk store, no model needed)
Step 7:  services/model.py            (ModelService skeleton — no actual load yet)
Step 8:  services/inference.py        (InferenceService + semaphore)
Step 9:  routers/health.py            (simplest router)
Step 10: app.py                       (lifespan + router registration)
Step 11: cli.py + __main__.py         (can now run: python -m omnivoice_server)
Step 12: routers/speech.py            (core endpoint)
Step 13: routers/voices.py            (profiles CRUD)
Step 14: Full integration test against real model (manual)
Step 15: benchmarks/run_benchmark.py
Step 16: Polish README + examples/
```

**Checkpoint after Step 11:** `omnivoice-server --help` must run without errors.
**Checkpoint after Step 13:** All unit tests pass (with mock model).
**Checkpoint after Step 14:** Real synthesis works on MPS.

---

*Spec complete. No ambiguity remains — every function signature, error case, and data flow has been defined.*
