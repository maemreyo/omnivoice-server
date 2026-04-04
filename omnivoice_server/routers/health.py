"""Health and metrics endpoints."""
from __future__ import annotations

import time

import psutil
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
