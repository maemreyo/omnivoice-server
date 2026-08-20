# Investigation Report: GitHub Issue #24 - CORS Policy Error

## 1. Problem Statement

**Issue**: CORS policy error when browser-based frontend (KoboldCpp at `localhost:5001`) attempts to call the omnivoice-server API at `127.0.0.1:8880`.

**Error from browser console**:
```
Access to fetch at 'http://127.0.0.1:8880/v1/audio/speech' from origin 'http://localhost:5001' 
has been blocked by CORS policy: Response to preflight request doesn't pass access control check: 
No 'Access-Control-Allow-Origin' header is present on the requested resource.
```

**Server log**:
```
127.0.0.1:8880 - "OPTIONS /v1/audio/speech HTTP/1.1" 405 Method Not Allowed
```

---

## 2. Root Cause Analysis

| Factor | Finding |
|--------|---------|
| **CORS Middleware** | **NOT PRESENT** - No `CORSMiddleware` configured anywhere |
| **Framework** | FastAPI (wraps Starlette's `CORSMiddleware`) |
| **Preflight Handling** | Returns `405 Method Not Allowed` - no `OPTIONS` route exists |
| **Response Headers** | Missing `Access-Control-Allow-*` headers on all responses |

### Technical Explanation

When a web page at `http://localhost:5001` makes a `fetch()` request to `http://127.0.0.1:8880`:

1. Browser sends **preflight** `OPTIONS` request first
2. Server has no CORS middleware → no `OPTIONS` handler → `405 Method Not Allowed`
3. Even if OPTIONS worked, no CORS headers would be present
4. Browser blocks the actual request

---

## 3. Evidence from Codebase

### `omnivoice_server/app.py` - No CORS middleware

```python
# Lines 107-121: Only auth middleware exists
if cfg.api_key:
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        # Skip auth for health, metrics, and model listing
        if request.url.path in ("/health", "/metrics", "/v1/models"):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {cfg.api_key}":
            return JSONResponse(...)
```

**Critical Issue**: Auth middleware does NOT skip OPTIONS requests. If `api_key` is set, preflight requests will be rejected with `401`.

### `omnivoice_server/config.py` - No CORS settings

All settings: `host`, `port`, `device`, `model`, `auth`, `streaming`...
**ZERO CORS-related fields exist.**

### `omnivoice_server/cli.py` - No CORS flags

All CLI args: `--host`, `--port`, `--api-key`, `--device`...
**ZERO CORS-related flags exist.**

### `omnivoice_server/routers/health.py` - No OPTIONS handling

```python
router = APIRouter()

@router.get("/health")
async def health(request: Request):
    """Readiness check. Returns 503 while model is loading, 200 when ready."""
    ...

@router.get("/metrics")
async def metrics(request: Request):
    """Request metrics and current memory usage."""
    ...
```

**Only `GET` methods defined** - no `@router.options` anywhere.

---

## 4. Router Architecture Summary

### HTTP Methods by Router

| Router | Methods | Endpoints |
|--------|---------|-----------|
| `speech.py` | `POST` | `/v1/audio/speech`, `/v1/audio/speech/clone` |
| `voices.py` | `GET`, `POST`, `PATCH`, `DELETE` | `/v1/voices`, `/v1/voices/profiles`, `/v1/voices/profiles/{id}` |
| `models.py` | `GET` | `/v1/models`, `/v1/models/{model_id}` |
| `script.py` | `POST` | `/v1/audio/script` |
| `health.py` | `GET` | `/health`, `/metrics` |

**Critical Finding**: **NO routers define `@router.options`** — there is **no explicit OPTIONS handling** anywhere in the codebase.

---

## 5. Solution Proposals

### Solution 1: Simple CORS Middleware (Quick Fix)

Add `CORSMiddleware` with permissive defaults for development.

```python
# app.py
from fastapi.middleware.cors import CORSMiddleware

def create_app(cfg: Settings) -> FastAPI:
    app = FastAPI(...)
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,  # ⚠️ This will FAIL - cannot use with "*"
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

**⚠️ Critical**: `allow_credentials=True` with `allow_origins=["*"]` raises `ValueError` at startup. FastAPI forbids this combination.

---

### Solution 2: Configurable CORS via Settings (Recommended)

Add proper CORS configuration following existing patterns.

**Changes**:

| File | Changes |
|------|---------|
| `config.py` | Add `cors_allow_origins`, `cors_allow_credentials` fields |
| `cli.py` | Add `--cors-origins` CLI flag |
| `app.py` | Add `CORSMiddleware` with config-based settings |

**Implementation**:

```python
# config.py - Add to Settings class
cors_allow_origins: list[str] = Field(
    default=["*"],
    description="Allowed CORS origins. Use ['*'] for all origins (dev only).",
)
cors_allow_credentials: bool = Field(
    default=False,
    description="Allow credentials. Cannot be True with ['*'].",
)
```

```python
# cli.py - Add argument
parser.add_argument(
    "--cors-origins",
    default=None,
    dest="cors_allow_origins",
    help="Comma-separated CORS origins (env: OMNIVOICE_CORS_ALLOW_ORIGINS)",
)
```

```python
# app.py - Add middleware
from fastapi.middleware.cors import CORSMiddleware

def create_app(cfg: Settings) -> FastAPI:
    app = FastAPI(...)
    
    # Add CORS middleware
    if cfg.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_allow_origins,
            allow_credentials=cfg.cors_allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )
```

---

### Solution 3: Production-Grade with Regex (Advanced)

For dynamic subdomain patterns (e.g., `*.example.com`).

```python
# config.py additions
cors_allow_origin_regex: str | None = Field(
    default=None,
    description="Regex pattern for dynamic origin matching.",
)

# app.py
if cfg.cors_allow_origins or cfg.cors_allow_origin_regex:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_allow_origins or [],
        allow_origin_regex=cfg.cors_allow_origin_regex,
        allow_credentials=cfg.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

---

## 6. Reference Examples (from OSS Projects)

| Project | Pattern |
|---------|---------|
| **vladmandic/sdnext** | CLI-based CORS with `--cors-origins` and `--cors-regex` flags |
| **OpenHands** | Custom `LocalhostCORSMiddleware` allowing localhost |
| **mlflow** | CORS as part of security middleware stack |
| **transformerlab** | Custom `DynamicCORSMiddleware` with domain checking |

---

## 7. FastAPI CORSMiddleware Reference

### Core Parameters

| Parameter | Type | Default | Production Guidance |
|-----------|------|---------|---------------------|
| `allow_origins` | `Sequence[str]` | `()` | List explicit origins. Never use `["*"]` with credentials. |
| `allow_methods` | `Sequence[str]` | `("GET",)` | Restrict to only needed methods |
| `allow_headers` | `Sequence[str]` | `()` | Restrict to only needed headers |
| `allow_credentials` | `bool` | `False` | `True` requires explicit origins (not wildcard) |
| `allow_origin_regex` | `str \| None` | `None` | Use for dynamic subdomain patterns |
| `expose_headers` | `Sequence[str]` | `()` | Headers browser can read from response |
| `max_age` | `int` | `600` | 600-3600s typical for production |

### Critical: `allow_credentials=True` Constraint

From FastAPI source, if `allow_credentials=True`:
- `allow_origins` **cannot** be `["*"]` → raises `ValueError` at startup
- Must use explicit origins or `allow_origin_regex` with specific patterns

---

## 8. Recommended Solution

**Solution 2 (Configurable CORS)** is recommended:

| Criterion | Score |
|-----------|-------|
| **Simplicity** | Moderate (~20 lines across 3 files) |
| **User Impact** | High - solves the reported issue immediately |
| **Security** | Good - allows restricting origins in production |
| **Compatibility** | Excellent - follows existing config patterns exactly |
| **Future-Proof** | Good - can extend with regex later |

**Usage after fix**:
```bash
# Development / browser frontend on another origin
omnivoice-server --cors-origins "http://localhost:5001,https://app.example.com"

# Or via env var
OMNIVOICE_CORS_ALLOW_ORIGINS="http://localhost:5001,https://app.example.com"
```

**Note**: The implemented default is an explicit local-development allowlist (`localhost`/`127.0.0.1` on ports `3000`, `5001`, and `5173`) rather than `"*"`, which is safer and avoids wildcard+credentials pitfalls.

---

## 9. Implementation Status

### Completed

- [x] Added `cors_allow_origins` and `cors_allow_credentials` fields to `Settings` in `config.py`
- [x] Added `--cors-origins`, `--cors-allow-credentials`, and `--no-cors-allow-credentials` in `cli.py`
- [x] Added `CORSMiddleware` configuration in `app.py`
- [x] Updated auth middleware so preflight `OPTIONS` requests are not blocked
- [x] Added CORS headers to `401` auth failures for allowed origins so browser clients see the auth error instead of a generic CORS failure
- [x] Documented CORS configuration and smoke-test commands in README sections

### Automated Verification

- `pytest tests/test_cors.py tests/test_speech.py`
- Result: `112 passed`

Covered cases include:

- allowed-origin preflight success
- disallowed-origin rejection
- requested-header reflection in preflight
- authenticated and unauthenticated browser-origin POST behavior
- wildcard and empty-origin config behavior
- settings parsing and invalid configuration validation

### Live Smoke Verification

Cross-origin smoke tests were executed against a live local server with:

- server origin: `http://127.0.0.1:8899`
- browser/test-page origin: `http://127.0.0.1:5001`

Observed results:

1. **Preflight** `OPTIONS /v1/audio/speech` returned `200 OK`
   - `Access-Control-Allow-Origin: http://127.0.0.1:5001`
   - `Access-Control-Allow-Headers: Content-Type,Authorization`

2. **Unauthorized POST** returned `401 Unauthorized`
   - still included `Access-Control-Allow-Origin: http://127.0.0.1:5001`
   - browser clients can surface the real auth failure

3. **Authorized POST** returned `200 OK`
   - included `Access-Control-Allow-Origin: http://127.0.0.1:5001`
   - included `Access-Control-Expose-Headers: X-Audio-Duration-S, X-Synthesis-Latency-S`

### Final Resolution

Issue #24's root cause was confirmed and is now resolved by configurable app-level CORS support plus auth/CORS interoperability fixes.

---

## 10. Related Files

| File | Path | Purpose |
|------|------|---------|
| Main App | `omnivoice_server/app.py` | FastAPI application factory |
| Config | `omnivoice_server/config.py` | Pydantic Settings |
| CLI | `omnivoice_server/cli.py` | Command-line interface |
| Speech Router | `omnivoice_server/routers/speech.py` | TTS endpoints |
| Health Router | `omnivoice_server/routers/health.py` | Health/metrics endpoints |
| Voices Router | `omnivoice_server/routers/voices.py` | Voice profile endpoints |
| Models Router | `omnivoice_server/routers/models.py` | Model listing endpoints |
| Script Router | `omnivoice_server/routers/script.py` | Script orchestration endpoints |

---

## 11. References

- [FastAPI CORS Documentation](https://fastapi.tiangolo.com/tutorial/cors/)
- [Starlette CORSMiddleware Source](https://github.com/encode/starlette)
- [FastAPI Middleware Reference](https://fastapi.tiangolo.com/reference/middleware/)
