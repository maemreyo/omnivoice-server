"""
FastAPI application factory.
All shared state lives on app.state — no module-level globals.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from .config import Settings
from .routers import health, models, speech, voices  # FIX: added models
from .services.batching import BatchingService
from .services.cache import AudioCache
from .services.inference import InferenceService
from .services.metrics import MetricsService
from .services.model import ModelService
from .services.profiles import ProfileService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg: Settings = app.state.cfg

    # ── Startup ──────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    logger.info("omnivoice-server starting up...")
    logger.info(
        f"  device={cfg.device}  num_step={cfg.num_step}  max_concurrent={cfg.max_concurrent}"
    )

    cfg.profile_dir.mkdir(parents=True, exist_ok=True)

    model_svc = ModelService(cfg)
    await model_svc.load()
    app.state.model_svc = model_svc

    # With batching: each batch is a single model.generate() call, so the
    # executor only needs enough threads for concurrent *batch dispatches*
    # (typically 1 for a single GPU).  max_concurrent still controls this.
    # Without batching: max_concurrent threads run individual requests, same
    # as the original design.
    executor = ThreadPoolExecutor(
        max_workers=cfg.max_concurrent,
        thread_name_prefix="omnivoice-infer",
    )

    # Dynamic batching: accumulate requests and dispatch as batched
    # model.generate() calls for better GPU utilisation.
    batching_svc = None
    if cfg.batch_enabled:
        batching_svc = BatchingService(
            model_svc=model_svc,
            executor=executor,
            cfg=cfg,
        )
        await batching_svc.start()
        app.state.batching_svc = batching_svc
        logger.info(
            f"Dynamic batching enabled (max_size={cfg.batch_max_size}, "
            f"timeout_ms={cfg.batch_timeout_ms}, "
            f"max_concurrent_batches={cfg.max_concurrent})"
        )
    else:
        logger.info(
            f"Dynamic batching disabled — single-request mode "
            f"(max_concurrent={cfg.max_concurrent})"
        )

    app.state.inference_svc = InferenceService(
        model_svc=model_svc,
        executor=executor,
        cfg=cfg,
        batching_svc=batching_svc,
    )

    app.state.profile_svc = ProfileService(profile_dir=cfg.profile_dir)
    app.state.metrics_svc = MetricsService()

    # Audio cache for repeated requests (same voice + text)
    if cfg.cache_enabled:
        audio_cache = AudioCache(cfg)
        await audio_cache.start()
        app.state.audio_cache = audio_cache
        logger.info(
            f"Audio cache enabled (max={cfg.cache_max_mb}MB, ttl={cfg.cache_ttl_s}s)"
        )
    else:
        app.state.audio_cache = None

    app.state.start_time = time.monotonic()

    elapsed = time.monotonic() - t0
    logger.info(f"Startup complete in {elapsed:.1f}s. Listening on http://{cfg.host}:{cfg.port}")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down...")
    if hasattr(app.state, "batching_svc") and app.state.batching_svc:
        await app.state.batching_svc.stop()
    audio_cache = getattr(app.state, "audio_cache", None)
    if audio_cache is not None:
        await audio_cache.stop()
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

    app.state.cfg = cfg

    # ── Auth middleware ───────────────────────────────────────────────────────
    if cfg.api_key:

        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):
            # Skip auth for health, metrics, and model listing
            if request.url.path in ("/health", "/metrics", "/v1/models"):
                return await call_next(request)
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {cfg.api_key}":
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"error": "Invalid or missing API key"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return await call_next(request)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(speech.router, prefix="/v1")
    app.include_router(voices.router, prefix="/v1")
    app.include_router(models.router, prefix="/v1")  # FIX: was missing
    app.include_router(health.router)

    return app
