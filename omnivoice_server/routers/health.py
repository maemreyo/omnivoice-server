"""Health and metrics endpoints."""

from __future__ import annotations

import time

import psutil
import torch
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
    model_svc = request.app.state.model_svc
    cfg = request.app.state.cfg
    snapshot = metrics_svc.snapshot()
    snapshot["ram_mb"] = round(psutil.Process().memory_info().rss / 1024 / 1024, 1)
    snapshot["cuda_alloc_conf"] = cfg.cuda_alloc_conf
    snapshot.update(model_svc.debug_snapshot())
    snapshot.update(_cuda_snapshot(cfg.device))
    return snapshot


def _cuda_snapshot(device: str) -> dict[str, float]:
    snapshot = {
        "cuda_allocated_mb": 0.0,
        "cuda_reserved_mb": 0.0,
        "cuda_max_allocated_mb": 0.0,
        "cuda_max_reserved_mb": 0.0,
        "cuda_free_mb": 0.0,
        "cuda_total_mb": 0.0,
        "cuda_used_mb_estimate": 0.0,
        "cuda_non_torch_mb_estimate": 0.0,
    }
    if device != "cuda" or not torch.cuda.is_available():
        return snapshot

    free_bytes, total_bytes = torch.cuda.mem_get_info()
    allocated_mb = torch.cuda.memory_allocated() / 1024 / 1024
    reserved_mb = torch.cuda.memory_reserved() / 1024 / 1024
    used_mb_estimate = (total_bytes - free_bytes) / 1024 / 1024

    snapshot["cuda_allocated_mb"] = round(allocated_mb, 1)
    snapshot["cuda_reserved_mb"] = round(reserved_mb, 1)
    snapshot["cuda_max_allocated_mb"] = round(torch.cuda.max_memory_allocated() / 1024 / 1024, 1)
    snapshot["cuda_max_reserved_mb"] = round(torch.cuda.max_memory_reserved() / 1024 / 1024, 1)
    snapshot["cuda_free_mb"] = round(free_bytes / 1024 / 1024, 1)
    snapshot["cuda_total_mb"] = round(total_bytes / 1024 / 1024, 1)
    snapshot["cuda_used_mb_estimate"] = round(used_mb_estimate, 1)
    snapshot["cuda_non_torch_mb_estimate"] = round(max(0.0, used_mb_estimate - reserved_mb), 1)
    return snapshot
