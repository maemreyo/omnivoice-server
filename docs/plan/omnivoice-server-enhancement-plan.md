# omnivoice-server — Enhancement Master Plan

**Version:** 1.0  
**Date:** 2026-04-05  
**Base commit:** `ec8b4a458d551949e369c9d127e36f6cd8bc67b8`  
**Scope:** Server-side enhancements only — không phụ thuộc vào consumer cụ thể

---

## 1. Tổng quan

omnivoice-server hiện tại là một FastAPI application hoạt động tốt trong môi trường development. Tuy nhiên, khi nhìn nhận như một standalone deployable service — dù là chạy trực tiếp trên máy user, trong Docker, hay được quản lý bởi process supervisor — một số vấn đề cơ bản về vận hành chưa được giải quyết.

Plan này tổ chức các enhancement theo 5 nhóm, đi từ nền tảng (runtime behavior) đến tính năng (API maturity), có thể thực hiện độc lập nhau.

---

## 2. Hiện trạng & Gap Analysis

| Hạng mục | Hiện trạng | Gap |
|----------|-----------|-----|
| Port binding | Cứng port 8880, không hỗ trợ OS auto-assign | Không thể chạy nhiều instance; conflict-prone |
| Startup announcement | Không có cơ chế thông báo port sau khi bind | Process supervisor không biết server ready ở đâu |
| Signal handling | Không có SIGTERM/SIGINT handler | Server không cleanup khi bị terminate |
| Logging | Mix stdout/stderr, không structured, không level | Không thể monitor, parse, hoặc route logs |
| Configuration | Một số params hardcoded, một số qua env var | Không nhất quán, khó deploy ở môi trường khác |
| Health check | `{"status": "healthy"}` trả về ngay cả khi model chưa load | False positive gây confusion cho monitoring |
| Memory footprint | ~1.7GB RAM trên CPU — không được document | User không có expectation, app crash âm thầm |
| Error responses | Một số endpoint trả empty body khi validation fail | Client không biết lý do thực sự |
| Storage | Profile directory hardcoded tương đối | Không portable, conflict khi nhiều instance |
| Model loading | Chưa rõ lazy vs eager loading | Latency spike trên request đầu tiên nếu lazy |

---

## 3. Enhancement Groups

---

### Group 1 — Runtime Behavior (Nền tảng)

**Mục tiêu:** Server phải hoạt động như một well-behaved Unix process.

#### 1.1 Dynamic Port Binding

**Vấn đề:** Port 8880 hardcoded. Nếu port bận, server crash thay vì fallback.

**Enhancement:**
- Khi `port = 0`, yêu cầu OS assign port available (ephemeral port)
- Khi port bận, log lý do rõ ràng và exit với non-zero code thay vì traceback

```python
# config.py
port: int = Field(default=8880, ge=0, le=65535)
# port=0 → OS assigns ephemeral port
```

**Acceptance:** Server start thành công với `OMNIVOICE_PORT=0` và bind được port.

---

#### 1.2 Startup Announcement

**Vấn đề:** Sau khi bind, không có cơ chế nào để caller biết server đang listen ở địa chỉ nào. Đặc biệt quan trọng khi dùng port dynamic.

**Enhancement:**

Ngay sau khi bind thành công, print ra stdout một dòng duy nhất theo format chuẩn:

```
OMNIVOICE_READY host=127.0.0.1 port=8880
```

Yêu cầu:
- Flush ngay (`flush=True`)
- Xuất hiện **trước** bất kỳ log nào khác
- Chỉ print một lần
- Stdout còn lại im lặng — toàn bộ logs đi stderr

**Lý do dùng key=value thay vì URL:** Dễ parse bằng regex, dễ extend thêm field sau (pid, version...) mà không break parser cũ.

**Acceptance:** `grep "OMNIVOICE_READY" <(python -m omnivoice_server)` trả về kết quả trong 10s.

---

#### 1.3 Graceful Shutdown

**Vấn đề:** Hiện không có signal handler. Khi nhận SIGTERM (từ systemd, supervisor, Docker stop...), Python terminate ngay, không cleanup.

**Enhancement:**

```python
# Trong lifespan hoặc signal handler
async def shutdown():
    # 1. Stop accepting new connections
    # 2. Wait for in-flight requests (timeout: 10s)
    # 3. Release model from memory
    # 4. Close any open file handles
    # 5. Exit code 0
```

Behavior:
- SIGTERM → graceful shutdown, exit 0, trong vòng 10s
- SIGINT (Ctrl+C) → tương tự SIGTERM
- Nếu in-flight requests không xong trong 10s → force exit, log warning

**Acceptance:** `kill -TERM <pid>` → server exit code 0 trong <10s; không còn process zombie.

---

#### 1.4 Startup Readiness — Model Loading

**Vấn đề:** Không rõ model được load khi nào (startup hay request đầu tiên). Nếu lazy loading, request đầu tiên sẽ có latency đột biến.

**Enhancement:**
- Model phải được load trong `lifespan` startup hook — không lazy
- `OMNIVOICE_READY` announcement chỉ được print **sau khi model load xong**
- Nếu model load fail, server exit với code 1 và log lý do rõ ràng

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await load_model()          # Block until loaded
    announce_ready()            # Then announce
    yield
    await release_model()
```

**Acceptance:** Request đầu tiên sau `OMNIVOICE_READY` không có cold-start latency.

---

### Group 2 — Observability

**Mục tiêu:** Server phải có thể được monitor và debug mà không cần attach debugger.

#### 2.1 Log Separation và Structure

**Vấn đề:** Logs hiện mix stdout/stderr. Không có level nhất quán. Không có format chuẩn.

**Enhancement:**

Tất cả application logs đi stderr theo format:

```
2026-04-05T11:23:26Z [INFO ] [startup] Model loaded: k2-fsa/OmniVoice (1.7GB RSS)
2026-04-05T11:23:26Z [INFO ] [server ] Listening on 127.0.0.1:8880
2026-04-05T11:25:01Z [INFO ] [request] POST /v1/audio/speech 200 842ms
2026-04-05T11:26:10Z [WARN ] [memory ] RSS 1.9GB — approaching threshold
2026-04-05T11:27:05Z [ERROR] [request] POST /v1/audio/speech/clone 413: ref_audio exceeds 25MB
```

Format: `<timestamp_iso8601> [<LEVEL>] [<component>] <message>`

Log levels: `DEBUG`, `INFO`, `WARN`, `ERROR` — configurable qua `OMNIVOICE_LOG_LEVEL`.

**Privacy constraint:** Không log nội dung text synthesis, không log ref audio content, không log voice profile data.

**Acceptance:** Chạy server và pipe stderr qua `grep "\[ERROR\]"` hoạt động chính xác.

---

#### 2.2 Health Check — Phân biệt Starting vs Ready

**Vấn đề:** `/health` trả `{"status": "healthy"}` ngay cả khi model chưa load. Process monitor nghĩ server ready khi thực ra chưa.

**Enhancement:**

```json
// Khi đang khởi động (model chưa load):
HTTP 503
{
  "status": "starting",
  "ready": false,
  "model_loaded": false
}

// Khi đã sẵn sàng:
HTTP 200
{
  "status": "healthy",
  "ready": true,
  "model_loaded": true,
  "uptime_s": 142,
  "model_id": "k2-fsa/OmniVoice"
}
```

HTTP 503 khi chưa ready — để load balancer / health monitor hiểu đúng trạng thái.

**Acceptance:** Poll `/health` liên tục từ lúc spawn; HTTP 200 chỉ xuất hiện sau khi model loaded.

---

#### 2.3 Memory Usage Logging

**Vấn đề:** Model chiếm ~1.7GB RAM nhưng không có visibility. Trên máy RAM thấp, OOM killer terminate server mà không có warning trước.

**Enhancement:**
- Log RSS khi model load xong: `[INFO] Model loaded, RSS: 1.7GB`
- Log warning khi RSS vượt ngưỡng: `[WARN] RSS 2.2GB — system may be under pressure`
- Expose RSS qua `/health` response (optional field `memory_rss_mb`)

**Acceptance:** Log file có entry RSS sau startup; không cần external monitoring để thấy memory usage.

---

### Group 3 — Configuration

**Mục tiêu:** Mọi thứ có thể thay đổi mà không cần sửa code. Tuân thủ 12-factor app principles.

#### 3.1 Unified Configuration

Tất cả config phải available qua environment variables, với prefix `OMNIVOICE_`:

| Variable | Type | Default | Mô tả |
|----------|------|---------|-------|
| `OMNIVOICE_HOST` | string | `127.0.0.1` | Bind host |
| `OMNIVOICE_PORT` | int | `8880` | Bind port; `0` = OS auto-assign |
| `OMNIVOICE_MODEL_ID` | string | `k2-fsa/OmniVoice` | HuggingFace model ID |
| `OMNIVOICE_MODEL_CACHE_DIR` | path | Platform default | Override HuggingFace cache location |
| `OMNIVOICE_PROFILES_DIR` | path | `./profiles` | Voice profile storage directory |
| `OMNIVOICE_LOG_LEVEL` | string | `INFO` | Log verbosity |
| `OMNIVOICE_MAX_CONCURRENT` | int | `1` | Max concurrent inference requests |
| `OMNIVOICE_SHUTDOWN_TIMEOUT` | int | `10` | Seconds to wait for in-flight requests on shutdown |

Tất cả đã được defined trong `config.py` (Pydantic Settings) — Enhancement là đảm bảo toàn bộ list này nhất quán, documented, và tested.

**Acceptance:** `OMNIVOICE_PROFILES_DIR=/tmp/test python -m omnivoice_server` → profiles được tạo trong `/tmp/test`.

---

#### 3.2 Storage Paths — Absolute, Not Relative

**Vấn đề:** `OMNIVOICE_PROFILES_DIR` default là `./profiles` — relative to CWD. Nếu server được spawn từ directory khác, profiles ở chỗ khác.

**Enhancement:**
- Default `profiles_dir` → absolute path dựa trên XDG Base Directory Specification:
  - Linux: `~/.local/share/omnivoice/profiles/`
  - macOS: `~/Library/Application Support/omnivoice/profiles/`
  - Windows: `%APPDATA%\omnivoice\profiles\`
- Log absolute path của profiles_dir khi startup

**Acceptance:** Server spawn từ `/` và `~` đều dùng cùng profiles directory.

---

### Group 4 — API Correctness

**Mục tiêu:** API trả lời đúng và đủ thông tin trong mọi trường hợp.

#### 4.1 Error Response Consistency

**Vấn đề:** Một số endpoint trả HTTP 400/413 với empty body hoặc plain text. Client không thể programmatically xử lý lỗi.

**Enhancement:**

Mọi error response phải có JSON body theo schema:

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

Error codes chuẩn:
- `validation_error` — input không hợp lệ
- `model_not_ready` — model chưa load xong (trả 503)
- `inference_failed` — lỗi trong quá trình synthesis
- `rate_limited` — quá max_concurrent requests
- `storage_error` — không thể đọc/ghi profiles

**Acceptance:** Mọi non-200 response đều có `Content-Type: application/json` và body hợp lệ.

---

#### 4.2 Request Size Validation — Fail Fast

**Vấn đề:** Clone mode nhận ref_audio tối đa 25MB. Hiện tại validation xảy ra sau khi upload xong — lãng phí bandwidth.

**Enhancement:**
- Check `Content-Length` header trước khi nhận body
- Trả 413 ngay nếu size vượt limit, không chờ upload
- Log: `[WARN] Rejected upload: Content-Length 30MB > limit 25MB`

**Acceptance:** `curl` với file 30MB bị reject trước khi upload hoàn tất.

---

#### 4.3 Clone Mode — Temp File Cleanup

**Vấn đề:** Clone mode có thể tạo temp files khi xử lý ref audio. Nếu inference fail hoặc server crash, temp files tồn tại mãi.

**Enhancement:**
- Dùng `tempfile.TemporaryDirectory()` với context manager — tự động cleanup
- Cleanup cả khi exception xảy ra trong inference
- Log temp dir creation và cleanup ở DEBUG level

**Acceptance:** Sau 1000 clone requests, không có orphan temp files trong `/tmp`.

---

### Group 5 — Documentation

**Mục tiêu:** Người vận hành có thể deploy và debug mà không cần đọc source code.

#### 5.1 System Requirements Document

Hiện tại không có document nào về hardware requirements. Cần tạo `docs/system/requirements.md`:

```markdown
## Minimum Requirements
- RAM: 8GB (model chiếm ~1.7GB; cần headroom cho OS và app)
- Disk: 5GB free (model ~3GB + runtime)
- CPU: x86_64 hoặc ARM64

## Recommended
- RAM: 16GB
- Disk: 10GB free
- CPU: 4+ cores (inference là single-threaded nhưng OS overhead)
```

#### 5.2 Configuration Reference

`docs/configuration.md` liệt kê toàn bộ env vars, default values, và ví dụ. Auto-generate từ Pydantic model nếu possible.

#### 5.3 Runbook — Common Issues

`docs/runbook.md` với troubleshooting cho:
- Server start nhưng inference fail (thiếu RAM)
- Port conflict (cách kiểm tra và giải quyết)
- Model download fail (network, disk space)
- Profile storage permission denied

---

## 4. Implementation Phases

### Phase 1 — Runtime Foundation (4–5 ngày)

Ưu tiên cao nhất. Không có những thứ này, server không thể được vận hành một cách đáng tin cậy.

| Task | File | Estimated |
|------|------|-----------|
| Dynamic port binding (`port=0`) | `config.py`, `cli.py` | 0.5 ngày |
| `OMNIVOICE_READY` stdout announcement | `app.py`, `cli.py` | 0.5 ngày |
| SIGTERM/SIGINT graceful shutdown | `app.py` | 1 ngày |
| Eager model loading trong lifespan | `services/model.py` | 0.5 ngày |
| Log separation (stdout/stderr) | `app.py`, logging config | 0.5 ngày |
| Structured logging với level | Logging config | 1 ngày |

### Phase 2 — Observability (2–3 ngày)

| Task | File | Estimated |
|------|------|-----------|
| Health check — starting vs ready | `routers/health.py` | 0.5 ngày |
| RSS logging trên startup | `services/model.py` | 0.5 ngày |
| Memory warning log | `services/metrics.py` | 0.5 ngày |
| `/health` response enrichment | `routers/health.py` | 0.5 ngày |

### Phase 3 — Configuration (1–2 ngày)

| Task | File | Estimated |
|------|------|-----------|
| Audit và chuẩn hóa env vars | `config.py` | 0.5 ngày |
| XDG-compliant default paths | `config.py` | 0.5 ngày |
| Validate paths tồn tại/writable khi startup | `app.py` | 0.5 ngày |

### Phase 4 — API Correctness (2–3 ngày)

| Task | File | Estimated |
|------|------|-----------|
| Error response schema chuẩn | `routers/`, exception handlers | 1 ngày |
| Fail-fast request size validation | `routers/speech.py` | 0.5 ngày |
| Clone mode temp file cleanup | `services/inference.py` | 0.5 ngày |

### Phase 5 — Documentation (1–2 ngày)

| Task | Output |
|------|--------|
| System requirements | `docs/system/requirements.md` |
| Configuration reference | `docs/configuration.md` |
| Runbook | `docs/runbook.md` |

---

## 5. Acceptance Criteria Tổng hợp

| Criterion | Test |
|-----------|------|
| Dynamic port | `OMNIVOICE_PORT=0 python -m omnivoice_server` → bind thành công |
| Ready announcement | stdout có `OMNIVOICE_READY host=... port=...` sau <10s |
| Announcement timing | `OMNIVOICE_READY` chỉ print sau khi model loaded |
| Graceful shutdown | `kill -TERM <pid>` → exit 0 trong <10s |
| Log separation | Stdout chỉ có `OMNIVOICE_READY`; mọi log khác ở stderr |
| Health starting | `/health` trả 503 khi model chưa load |
| Health ready | `/health` trả 200 + `ready:true` sau khi model loaded |
| Error body | Mọi 4xx/5xx có JSON body với `error.code` và `error.message` |
| Profiles dir | `OMNIVOICE_PROFILES_DIR=/tmp/x` → profiles trong `/tmp/x`, không phải `./profiles` |
| Temp cleanup | 1000 clone requests → 0 orphan temp files |
| No sensitive log | Grep log file → không có text synthesis content |

---

## 6. Non-Goals

Những thứ nằm ngoài scope của plan này:

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
| Phase 1 — Runtime Foundation | 4–5 ngày |
| Phase 2 — Observability | 2–3 ngày |
| Phase 3 — Configuration | 1–2 ngày |
| Phase 4 — API Correctness | 2–3 ngày |
| Phase 5 — Documentation | 1–2 ngày |
| **Total** | **10–15 ngày (2–3 tuần)** |

Các phase có thể chạy song song một phần (Phase 3 và 4 độc lập nhau). Phase 1 phải hoàn thành trước Phase 2.

---

*Document owner: omnivoice-server team*  
*Base commit: `ec8b4a458d551949e369c9d127e36f6cd8bc67b8`*
