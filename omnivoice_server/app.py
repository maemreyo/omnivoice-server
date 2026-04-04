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
        f"  device={cfg.device}  num_step={cfg.num_step}  "
        f"max_concurrent={cfg.max_concurrent}"
    )

    cfg.profile_dir.mkdir(parents=True, exist_ok=True)

    model_svc = ModelService(cfg)
    await model_svc.load()
    app.state.model_svc = model_svc

    executor = ThreadPoolExecutor(
        max_workers=cfg.max_concurrent,
        thread_name_prefix="omnivoice-infer",
    )
    app.state.inference_svc = InferenceService(
        model_svc=model_svc,
        executor=executor,
        cfg=cfg,
    )

    app.state.profile_svc = ProfileService(profile_dir=cfg.profile_dir)
    app.state.metrics_svc = MetricsService()
    app.state.start_time = time.monotonic()

    elapsed = time.monotonic() - t0
    logger.info(
        f"Startup complete in {elapsed:.1f}s. "
        f"Listening on http://{cfg.host}:{cfg.port}"
    )

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
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
    app.include_router(models.router, prefix="/v1")   # FIX: was missing
    app.include_router(health.router)

    return app
