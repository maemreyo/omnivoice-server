# omnivoice-server — Enhancement Master Plan

**Version:** 1.0  
**Date:** 2026-04-05  
**Base commit:** `ec8b4a458d551949e369c9d127e36f6cd8bc67b8`  
**Scope:** Server-side enhancements only — agnostic to any specific consumer

---

## 1. Overview

omnivoice-server currently is a FastAPI application that works well in development environments. However, when viewed as a standalone deployable service — whether running directly on a user's machine, in Docker, or managed by a process supervisor — several fundamental operational issues remain unaddressed.

This plan organizes enhancements into 5 groups, ranging from runtime behavior (the foundation) to API maturity (features), which can be implemented independently.

---

## 2. Current State & Gap Analysis

| Category | Current State | Gap |
|----------|---------------|-----|
| Port binding | Hardcoded to port 8880, no support for OS auto-assignment | Cannot run multiple instances; conflict-prone |
| Startup announcement | No mechanism to announce the port after binding | Process supervisor doesn't know where the server is ready |
| Signal handling | No SIGTERM/SIGINT handlers | Server doesn't clean up when terminated |
| Logging | Mix of stdout/stderr, unstructured, no levels | Impossible to monitor, parse, or route logs |
| Configuration | Some params hardcoded, some via env vars | Inconsistent, difficult to deploy in different environments |
| Health check | `{"status": "healthy"}` returns even if model isn't loaded | False positives cause confusion for monitoring |
| Memory footprint | ~1.7GB RAM on CPU — undocumented | Users have no expectations; app crashes silently |
| Error responses | Some endpoints return empty bodies on validation failure | Client doesn't know the actual reason |
| Storage | Profile directory hardcoded relatively | Not portable, conflicts with multiple instances |
| Model loading | Unclear lazy vs. eager loading | Latency spikes on the first request if lazy |

---

## 3. Enhancement Groups

---

### Group 1 — Runtime Behavior (Foundation)

**Goal:** The server must act like a well-behaved Unix process.

#### 1.1 Dynamic Port Binding

**Problem:** Port 8880 is hardcoded. If the port is busy, the server crashes instead of falling back.

**Enhancement:**
- When `port = 0`, request the OS to assign an available port (ephemeral port).
- When the port is busy, log a clear reason and exit with a non-zero code instead of a traceback.

```python
# config.py
port: int = Field(default=8880, ge=0, le=65535)
# port=0 → OS assigns ephemeral port
```

**Acceptance:** Server starts successfully with `OMNIVOICE_PORT=0` and binds to a port.

---

#### 1.2 Startup Announcement

**Problem:** After binding, there's no mechanism for the caller to know which address the server is listening on. This is especially important when using dynamic ports.

**Enhancement:**

Immediately after a successful bind, print a single line to stdout in a standard format:

```
OMNIVOICE_READY host=127.0.0.1 port=8880
```

Requirements:
- Flush immediately (`flush=True`).
- Appears **before** any other logs.
- Printed only once.
- Remaining stdout is silent — all logs go to stderr.

**Reason for using key=value instead of URL:** Easier to parse with regex, easier to extend with more fields later (pid, version...) without breaking old parsers.

**Acceptance:** `grep "OMNIVOICE_READY" <(python -m omnivoice_server)` returns a result within 10s.

---

#### 1.3 Graceful Shutdown

**Problem:** Currently no signal handlers. When receiving SIGTERM (from systemd, supervisor, Docker stop...), Python terminates immediately without cleanup.

**Enhancement:**

```python
# Within lifespan or signal handler
async def shutdown():
    # 1. Stop accepting new connections
    # 2. Wait for in-flight requests (timeout: 10s)
    # 3. Release model from memory
    # 4. Close any open file handles
    # 5. Exit code 0
```

Behavior:
- SIGTERM → graceful shutdown, exit 0, within 10s.
- SIGINT (Ctrl+C) → same as SIGTERM.
- If in-flight requests don't finish within 10s → force exit, log warning.

**Acceptance:** `kill -TERM <pid>` → server exits with code 0 in < 10s; no zombie processes left.

---

#### 1.4 Startup Readiness — Model Loading

**Problem:** Unclear when the model is loaded (at startup or first request). If lazy loading, the first request will have a significant latency spike.

**Enhancement:**
- The model must be loaded in the `lifespan` startup hook — no lazy loading.
- The `OMNIVOICE_READY` announcement is only printed **after the model is fully loaded**.
- If model loading fails, the server exits with code 1 and logs a clear reason.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await load_model()          # Block until loaded
    announce_ready()            # Then announce
    yield
    await release_model()
```

**Acceptance:** The first request after `OMNIVOICE_READY` has no cold-start latency.

---

### Group 2 — Observability

**Goal:** The server must be monitorable and debuggable without attaching a debugger.

#### 2.1 Log Separation and Structure

**Problem:** Logs are currently mixed between stdout/stderr. No consistent levels. No standard format.

**Enhancement:**

All application logs go to stderr in the format:

```
2026-04-05T11:23:26Z [INFO ] [startup] Model loaded: k2-fsa/OmniVoice (1.7GB RSS)
2026-04-05T11:23:26Z [INFO ] [server ] Listening on 127.0.0.1:8880
2026-04-05T11:25:01Z [INFO ] [request] POST /v1/audio/speech 200 842ms
2026-04-05T11:26:10Z [WARN ] [memory ] RSS 1.9GB — approaching threshold
2026-04-05T11:27:05Z [ERROR] [request] POST /v1/audio/speech/clone 413: ref_audio exceeds 25MB
```

Format: `<timestamp_iso8601> [<LEVEL>] [<component>] <message>`

Log levels: `DEBUG`, `INFO`, `WARN`, `ERROR` — configurable via `OMNIVOICE_LOG_LEVEL`.

**Privacy constraint:** Do not log synthesis text content, do not log ref audio content, do not log voice profile data.

**Acceptance:** Running the server and piping stderr through `grep "\[ERROR\]"` works correctly.

---

#### 2.2 Health Check — Distinguishing Starting vs. Ready

**Problem:** `/health` returns `{"status": "healthy"}` even if the model isn't loaded. The process monitor thinks the server is ready when it actually isn't.

**Enhancement:**

```json
// During startup (model not loaded):
HTTP 503
{
  "status": "starting",
  "ready": false,
  "model_loaded": false
}

// When ready:
HTTP 200
{
  "status": "healthy",
  "ready": true,
  "model_loaded": true,
  "uptime_s": 142,
  "model_id": "k2-fsa/OmniVoice"
}
```

HTTP 503 when not ready — so load balancers / health monitors correctly understand the state.

**Acceptance:** Polling `/health` continuously from spawn; HTTP 200 only appears after the model is loaded.

---

#### 2.3 Memory Usage Logging

**Problem:** The model takes ~1.7GB RAM but has no visibility. On low-RAM machines, the OOM killer terminates the server without prior warning.

**Enhancement:**
- Log RSS after model loading: `[INFO] Model loaded, RSS: 1.7GB`.
- Log warning when RSS exceeds a threshold: `[WARN] RSS 2.2GB — system may be under pressure`.
- Expose RSS via `/health` response (optional field `memory_rss_mb`).

**Acceptance:** Log file contains RSS entries after startup; no external monitoring needed to see memory usage.

---

### Group 3 — Configuration

**Goal:** Everything should be changeable without modifying code. Adhere to 12-factor app principles.

#### 3.1 Unified Configuration

All configuration must be available via environment variables, prefixed with `OMNIVOICE_`:

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OMNIVOICE_HOST` | string | `127.0.0.1` | Bind host |
| `OMNIVOICE_PORT` | int | `8880` | Bind port; `0` = OS auto-assign |
| `OMNIVOICE_MODEL_ID` | string | `k2-fsa/OmniVoice` | HuggingFace model ID |
| `OMNIVOICE_MODEL_CACHE_DIR` | path | Platform default | Override HuggingFace cache location |
| `OMNIVOICE_PROFILES_DIR` | path | `./profiles` | Voice profile storage directory |
| `OMNIVOICE_LOG_LEVEL` | string | `INFO` | Log verbosity |
| `OMNIVOICE_MAX_CONCURRENT` | int | `1` | Max concurrent inference requests |
| `OMNIVOICE_SHUTDOWN_TIMEOUT` | int | `10` | Seconds to wait for in-flight requests on shutdown |

Everything has been defined in `config.py` (Pydantic Settings) — The enhancement is to ensure this entire list is consistent, documented, and tested.

**Acceptance:** `OMNIVOICE_PROFILES_DIR=/tmp/test python -m omnivoice_server` → profiles are created in `/tmp/test`.

---

#### 3.2 Storage Paths — Absolute, Not Relative

**Problem:** `OMNIVOICE_PROFILES_DIR` defaults to `./profiles` — relative to CWD. If the server is spawned from a different directory, profiles end up elsewhere.

**Enhancement:**
- Default `profiles_dir` → absolute path based on XDG Base Directory Specification:
  - Linux: `~/.local/share/omnivoice/profiles/`
  - macOS: `~/Library/Application Support/omnivoice/profiles/`
  - Windows: `%APPDATA%\omnivoice\profiles\`
- Log the absolute path of `profiles_dir` at startup.

**Acceptance:** Server spawn from `/` or `~` uses the same profiles directory.

---

### Group 4 — API Correctness

**Goal:** The API responds correctly and with sufficient information in all cases.

#### 4.1 Error Response Consistency

**Problem:** Some endpoints return HTTP 400/413 with empty bodies or plain text. Clients cannot handle errors programmatically.

**Enhancement:**

Every error response must have a JSON body following the schema:

```json
{
  "error": {
    "code": "validation_error",
    "message": "ref_audio exceeds maximum size of 25MB",
    "field": "ref_audio",
    "detail": {}
  }
}
```

Standard error codes:
- `validation_error` — invalid input.
- `model_not_ready` — model hasn't finished loading (returns 503).
- `inference_failed` — error during synthesis.
- `rate_limited` — exceeded max_concurrent requests.
- `storage_error` — cannot read/write profiles.

**Acceptance:** Every non-200 response has `Content-Type: application/json` and a valid body.

---

#### 4.2 Request Size Validation — Fail Fast

**Problem:** Clone mode accepts ref_audio up to 25MB. Currently, validation happens after the upload completes — wasting bandwidth.

**Enhancement:**
- Check the `Content-Length` header before accepting the body.
- Return 413 immediately if the size exceeds the limit, without waiting for the upload.
- Log: `[WARN] Rejected upload: Content-Length 30MB > limit 25MB`.

**Acceptance:** `curl` with a 30MB file is rejected before the upload completes.

---

#### 4.3 Clone Mode — Temp File Cleanup

**Problem:** Clone mode can create temporary files when processing ref audio. If inference fails or the server crashes, temp files persist forever.

**Enhancement:**
- Use `tempfile.TemporaryDirectory()` with a context manager — automatic cleanup.
- Clean up even when an exception occurs during inference.
- Log temp dir creation and cleanup at the DEBUG level.

**Acceptance:** After 1000 clone requests, there are no orphan temp files in `/tmp`.

---

### Group 5 — Documentation

**Goal:** Operators can deploy and debug without reading source code.

#### 5.1 System Requirements Document

Currently, there is no documentation on hardware requirements. Create `docs/system/requirements.md`:

```markdown
## Minimum Requirements
- RAM: 8GB (model takes ~1.7GB; need headroom for OS and app)
- Disk: 5GB free (model ~3GB + runtime)
- CPU: x86_64 or ARM64

## Recommended
- RAM: 16GB
- Disk: 10GB free
- CPU: 4+ cores (inference is single-threaded but OS overhead exists)
```

#### 5.2 Configuration Reference

`docs/configuration.md` lists all env vars, default values, and examples. Auto-generate from the Pydantic model if possible.

#### 5.3 Runbook — Common Issues

`docs/runbook.md` with troubleshooting for:
- Server starts but inference fails (insufficient RAM).
- Port conflict (how to check and resolve).
- Model download failure (network, disk space).
- Profile storage permission denied.

---

## 4. Implementation Phases

### Phase 1 — Runtime Foundation (4–5 days)

Highest priority. Without these, the server cannot be operated reliably.

| Task | File | Estimated |
|------|------|-----------|
| Dynamic port binding (`port=0`) | `config.py`, `cli.py` | 0.5 days |
| `OMNIVOICE_READY` stdout announcement | `app.py`, `cli.py` | 0.5 days |
| SIGTERM/SIGINT graceful shutdown | `app.py` | 1 day |
| Eager model loading in lifespan | `services/model.py` | 0.5 days |
| Log separation (stdout/stderr) | `app.py`, logging config | 0.5 days |
| Structured logging with levels | Logging config | 1 day |

### Phase 2 — Observability (2–3 days)

| Task | File | Estimated |
|------|------|-----------|
| Health check — starting vs ready | `routers/health.py` | 0.5 days |
| RSS logging on startup | `services/model.py` | 0.5 days |
| Memory warning log | `services/metrics.py` | 0.5 days |
| `/health` response enrichment | `routers/health.py` | 0.5 days |

### Phase 3 — Configuration (1–2 days)

| Task | File | Estimated |
|------|------|-----------|
| Audit and standardize env vars | `config.py` | 0.5 days |
| XDG-compliant default paths | `config.py` | 0.5 days |
| Validate path existence/writability on startup | `app.py` | 0.5 days |

### Phase 4 — API Correctness (2–3 days)

| Task | File | Estimated |
|------|------|-----------|
| Standard error response schema | `routers/`, exception handlers | 1 day |
| Fail-fast request size validation | `routers/speech.py` | 0.5 days |
| Clone mode temp file cleanup | `services/inference.py` | 0.5 days |

### Phase 5 — Documentation (1–2 days)

| Task | Output |
|------|--------|
| System requirements | `docs/system/requirements.md` |
| Configuration reference | `docs/configuration.md` |
| Runbook | `docs/runbook.md` |

---

## 5. Summary Acceptance Criteria

| Criterion | Test |
|-----------|------|
| Dynamic port | `OMNIVOICE_PORT=0 python -m omnivoice_server` → bind successful |
| Ready announcement | stdout has `OMNIVOICE_READY host=... port=...` after < 10s |
| Announcement timing | `OMNIVOICE_READY` only prints after model is loaded |
| Graceful shutdown | `kill -TERM <pid>` → exit 0 in < 10s |
| Log separation | stdout has only `OMNIVOICE_READY`; all other logs in stderr |
| Health starting | `/health` returns 503 while model is loading |
| Health ready | `/health` returns 200 + `ready:true` after model is loaded |
| Error body | All 4xx/5xx have JSON body with `error.code` and `error.message` |
| Profiles dir | `OMNIVOICE_PROFILES_DIR=/tmp/x` → profiles in `/tmp/x`, not `./profiles` |
| Temp cleanup | 1000 clone requests → 0 orphan temp files |
| No sensitive logs | grep log file → no synthesis text content |

---

## 6. Non-Goals

Things outside the scope of this plan:

- GPU support
- Streaming TTS (real-time output)
- Multi-model support
- Authentication / API keys
- Horizontal scaling / clustering
- Web UI
- Voice model training / fine-tuning

---

## 7. Estimated Effort

| Phase | Effort |
|-------|--------|
| Phase 1 — Runtime Foundation | 4–5 days |
| Phase 2 — Observability | 2–3 days |
| Phase 3 — Configuration | 1–2 days |
| Phase 4 — API Correctness | 2–3 days |
| Phase 5 — Documentation | 1–2 days |
| **Total** | **10–15 days (2–3 weeks)** |

Phases can partially run in parallel (Phases 3 and 4 are independent). Phase 1 must be completed before Phase 2.

---

*Document owner: omnivoice-server team*  
*Base commit: `ec8b4a458d551949e369c9d127e36f6cd8bc67b8`*
