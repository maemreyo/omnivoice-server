"""
FastAPI application factory.
All shared state lives on app.state — no module-level globals.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import Settings
from .routers import health, models, script, speech, voices
from .services.inference import InferenceService
from .services.metrics import MetricsService
from .services.model import ModelService
from .services.profiles import ProfileService
from .services.script import ScriptOrchestrator

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
    app.state.script_orchestrator = ScriptOrchestrator(
        inference_service=app.state.inference_svc,
        profile_service=app.state.profile_svc,
        metrics_service=app.state.metrics_svc,
        settings=cfg,
    )
    app.state.start_time = time.monotonic()

    elapsed = time.monotonic() - t0
    logger.info(f"Startup complete in {elapsed:.1f}s. Listening on http://{cfg.host}:{cfg.port}")

    # Announce readiness to stdout (for process supervisors/callers to detect port)
    print(f"OMNIVOICE_READY host={cfg.host} port={cfg.port}", flush=True)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down...")
    executor.shutdown(wait=False)
    logger.info("Done.")


def _status_to_code(status_code: int) -> str:
    _map = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        413: "payload_too_large",
        422: "validation_error",
        500: "inference_failed",
        503: "model_not_ready",
        504: "timeout",
    }
    return _map.get(status_code, f"http_{status_code}")


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

    # ── Global error handlers ─────────────────────────────────────────────────
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Use mode='json' to ensure all values are JSON-serializable
        # (avoids ValueError objects in 'ctx' from field_validator)
        try:
            errors = exc.errors(include_url=False)
            # Ensure ctx values are strings
            for err in errors:
                if "ctx" in err:
                    err["ctx"] = {k: str(v) for k, v in err["ctx"].items()}
        except Exception:
            errors = [{"msg": "validation error"}]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "detail": errors,
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": _status_to_code(exc.status_code),
                    "message": exc.detail,
                }
            },
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(speech.router, prefix="/v1")
    app.include_router(voices.router, prefix="/v1")
    app.include_router(models.router, prefix="/v1")
    app.include_router(script.router, prefix="/v1")
    app.include_router(health.router)

    return app
