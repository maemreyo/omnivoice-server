# Multi-Speaker Script API - Technical Specification

**Document Version**: 1.1  
**Date**: 2026-04-17  
**Author**: Technical Team  
**Status**: Revised — Pending Final Approval

**Revision History**:
- v1.0 (2026-04-17): Initial draft
- v1.1 (2026-04-17): Address review gaps C1–C4, M1–M7, m1–m6

---

## Executive Summary

This document proposes a new Multi-Speaker Script API endpoint (`POST /v1/audio/script`) for omnivoice-server that enables synthesis of dialogue and multi-speaker content. The feature addresses a critical gap: while OmniVoice excels at single-voice synthesis, it lacks native support for generating conversations with multiple distinct speakers in a single request.

**Key Points:**
- **Problem**: Current API requires separate synthesis calls per speaker, then manual audio mixing
- **Solution**: New endpoint that orchestrates multi-speaker synthesis with automatic audio mixing
- **Approach**: Post-processing strategy (synthesize segments sequentially, mix audio)
- **Target Use Cases**: Audiobooks, podcasts, game dialogues, IVR announcements
- **Estimated Effort**: 6-9 days end-to-end implementation

---

## Table of Contents

1. [Background](#1-background)
2. [Current State Analysis](#2-current-state-analysis)
3. [Problem Statement](#3-problem-statement)
4. [Proposed Solution](#4-proposed-solution)
5. [API Design](#5-api-design)
6. [Architecture & Implementation](#6-architecture--implementation)
7. [Design Decisions & Rationale](#7-design-decisions--rationale)
8. [Implementation Plan](#8-implementation-plan)
9. [Testing & Validation](#9-testing--validation)
10. [Future Considerations](#10-future-considerations)
11. [Appendix](#11-appendix)

---

## 1. Background

### 1.1 What is OmniVoice?

OmniVoice is a state-of-the-art massively multilingual zero-shot text-to-speech (TTS) model developed by k2-fsa, supporting over 600 languages. Built on a diffusion language model architecture, it provides:

**Core Capabilities:**
- **Voice Cloning**: Generate speech matching a reference audio sample (3-10 seconds)
- **Voice Design**: Control voice characteristics via text attributes (gender, age, pitch, accent, dialect)
- **Auto Voice**: Automatic voice selection when no reference provided
- **Advanced Control**: Non-verbal symbols (`[laughter]`, `[sigh]`), pronunciation correction (Pinyin/CMU phonemes)
- **High Performance**: RTF as low as 0.025 (40x faster than real-time)

**Generation Parameters:**
| Parameter | Description | Default |
|-----------|-------------|---------|
| `num_step` | Diffusion steps | 32 |
| `speed` | Speaking rate factor (>1 faster, <1 slower) | 1.0 |
| `duration` | Fixed output duration (seconds) | auto-estimated |
| `guidance_scale` | Classifier-free guidance | 2.0 |
| `t_shift` | Time-step shift | 0.1 |
| `audio_chunk_duration` | Chunk size for long text | 15.0s |

**Additional Features:**
- Non-verbal symbols: `[laughter]`, `[sigh]`, `[question-en]`, etc.
- Pronunciation correction via pinyin (Chinese) or CMU phonemes (English)
- 600+ languages supported

**Technical Architecture:**
- Base model: Diffusion Language Model (Qwen/Qwen3-0.6B)
- Audio tokenizer: HiggsAudioV2 (24kHz output)
- Generation: Non-autoregressive diffusion process
- **Key Limitation**: Single-voice-per-generation design

**What OmniVoice Does NOT Support:**
- ❌ Multi-speaker dialogue in single call
- ❌ Turn-based conversation synthesis
- ❌ Speaker switching within generation
- ❌ Parameters like `voice2`, `turn_prefix`, `speaker_ids`

**Evidence**: Analysis of `OmniVoice.generate()` signature (omnivoice/models/omnivoice.py:458-527) shows no multi-speaker parameters. The `VoiceClonePrompt` dataclass (line 84-88) contains a single reference audio, and batch processing (`text: list[str]`) applies the same voice to all items due to `_ensure_list` auto-repeat behavior.

**Batch Processing Constraint**: OmniVoice accepts `list[str]` for batch processing, but all items must share the **same voice configuration**. You cannot pass different voices per item in a batch.

### 1.2 What is omnivoice-server?

omnivoice-server is an OpenAI-compatible HTTP server wrapper for OmniVoice, providing production-ready TTS infrastructure.

**Current Features:**
- **Voice Synthesis Modes**: Design mode (via instructions/attributes), Clone mode (one-shot from reference audio)
- **Voice Selection**: Default auto voice, OpenAI presets (`alloy`, `echo`, `nova`, etc.), saved voice profiles
- **Output Formats**: wav, mp3, opus, flac, aac, pcm
- **Streaming**: Sentence-level chunked PCM transfer
- **Voice Profiles**: Persistent storage for cloned voices (filesystem-based)
- **Advanced Parameters**: Full exposure of OmniVoice generation params (guidance_scale, denoise, t_shift, etc.)

**Architecture:**
```
FastAPI (1 uvicorn worker)
    │
    ├── InferenceService (async wrapper)
    │       └── ThreadPoolExecutor(max_workers=MAX_CONCURRENT)
    │               └── semaphore.acquire() → blocking model.generate()
    │
    ├── ProfileService (voice profiles CRUD)
    ├── MetricsService (latency/timeouts/errors tracking)
    └── audio.py (pydub + ffmpeg format conversion)
```

**Concurrency Model:**
- Default `MAX_CONCURRENT=2` (configurable via Settings, range 1-16)
- `asyncio.Semaphore(cfg.max_concurrent)` initialized in `InferenceService.__init__`
- Each `synthesize()` call does `async with self._semaphore:` — blocks if budget exhausted
- `asyncio.wait_for(..., timeout=cfg.request_timeout_s)` wraps each synthesis (default 120s)
- ThreadPoolExecutor runs blocking inference off async event loop

**Auth Middleware:**
```python
# app.py lines 99–114
if cfg.api_key:
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
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
```
Applied globally via `@app.middleware("http")` — all endpoints (including the new script endpoint) automatically inherit this auth.

**MetricsService Interface:**
```python
metrics.record_success(latency_s: float)
metrics.record_error()
metrics.record_timeout()
metrics.snapshot()  # → dict with totals, mean_latency_ms, p95_latency_ms
```

**Key Design Decisions:**
- Single uvicorn worker (GPU/MPS inference must load model into each process)
- Sentence-level streaming (splits text at sentence boundaries)
- Profile storage: Filesystem-based (WAV + metadata JSON)

**Limitations Relevant to Multi-Speaker:**
- ❌ Single speaker per request
- ❌ No script/turn-taking concept
- ❌ No built-in audio mixing for multiple voices

---

## 2. Current State Analysis

### 2.1 Existing Endpoints

| Endpoint | Method | Purpose | Reference |
|----------|--------|---------|----------|
| `/v1/audio/speech` | POST | OpenAI-compatible TTS (design/clone modes) | `routers/speech.py` |
| `/v1/audio/speech/clone` | POST | One-shot voice cloning (multipart upload) | `routers/speech.py` |
| `/v1/voices` | GET | List available voices (presets + profiles) | `routers/voices.py` |
| `/v1/voices/profiles` | POST | Create voice cloning profile | `routers/voices.py` |
| `/v1/voices/profiles/{id}` | GET/PATCH/DELETE | Profile CRUD operations | `routers/voices.py` |
| `/health` | GET | Health check | `routers/health.py` |
| `/metrics` | GET | JSON metrics (latency, errors, timeouts) | `routers/health.py` |

### 2.2 Current Workflow for Multi-Speaker Content

**Today's approach** (manual, client-side):
```bash
# Step 1: Synthesize speaker 1
curl -X POST /v1/audio/speech \
  -d '{"input": "Hello!", "voice": "clone:alice"}' \
  --output alice.wav

# Step 2: Synthesize speaker 2  
curl -X POST /v1/audio/speech \
  -d '{"input": "Hi there!", "voice": "design:male,british"}' \
  --output bob.wav

# Step 3: Manual audio mixing (ffmpeg, Audacity, etc.)
ffmpeg -i alice.wav -i bob.wav -filter_complex "[0][1]concat=n=2:v=0:a=1" output.wav
```

**Problems:**
- 3+ API calls for simple dialogue
- Client must handle audio mixing
- No automatic pause insertion
- Error-prone for long scripts (50+ segments)
- Poor developer experience

---

## 3. Problem Statement

### 3.1 User Need

Users need to generate multi-speaker audio content (audiobooks, podcasts, game dialogues, IVR) efficiently without manual post-processing.

**Target Use Cases:**
1. **Audiobooks**: Narrator + character voices
2. **Podcasts**: 2-3 hosts in conversation
3. **Game Dialogues**: NPC conversations
4. **IVR/Phone Systems**: Multi-agent announcements
5. **Educational Content**: Teacher-student dialogues

### 3.2 Gap Analysis

| Capability | OmniVoice Library | omnivoice-server | Gap |
|------------|-------------------|------------------|-----|
| Single-voice synthesis | ✅ | ✅ | None |
| Voice cloning | ✅ | ✅ | None |
| Voice design | ✅ | ✅ | None |
| **Multi-speaker dialogue** | ❌ | ❌ | **Critical** |
| Audio mixing | ❌ | ❌ | **Critical** |
| Pause control | Partial | Partial | Medium |

---

## 4. Proposed Solution

### 4.1 Solution Overview

Implement a new endpoint `POST /v1/audio/script` that:
1. Accepts a script with multiple speaker segments
2. Resolves voice for each speaker (clone/design/preset)
3. Synthesizes each segment sequentially
4. Inserts configurable pauses between speakers
5. Mixes audio into single track or returns separate tracks

**Approach**: Post-processing strategy (not model-level) because:
- OmniVoice model does not support native multi-speaker
- Works with current model without modifications
- Provides full control over mixing and pauses
- Can be upgraded to model-level when/if OmniVoice adds support

### 4.2 High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│              POST /v1/audio/script                      │
├─────────────────────────────────────────────────────────┤
│  Request: { script: [...], output_format, pause }       │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  1. Validate script (limits, speaker IDs, voices)       │
│  2. Resolve voices upfront (clone lookup + validate)    │
│  3. Synthesize segments (sequential, 1 semaphore slot)  │
│  4. Insert pauses on speaker change                     │
│  5. Mix audio (single_track or multi_track)             │
│  6. Convert to requested format (wav/mp3/opus/etc)      │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## 5. API Design

### 5.1 Request Schema

```json
POST /v1/audio/script
Content-Type: application/json
Authorization: Bearer <api_key>

{
  "script": [
    {
      "speaker": "alice",
      "voice": "clone:alice_profile",
      "text": "Hello Bob! How are you today?"
    },
    {
      "speaker": "bob", 
      "voice": "design:male,deep,british accent",
      "text": "Hi Alice! I'm doing great, thanks for asking."
    },
    {
      "speaker": "alice",
      "text": "That's wonderful to hear!"
    }
  ],
  "output_format": "single_track",
  "pause_between_speakers": 0.5,
  "response_format": "mp3",
  "speed": 1.0,
  "on_error": "abort"
}
```

**Field Definitions:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `script` | `array[ScriptSegment]` | ✅ | — | List of speaker segments (1–100) |
| `output_format` | `"single_track" \| "multi_track"` | ❌ | `"single_track"` | Audio output mode |
| `pause_between_speakers` | `float` | ❌ | `0.5` | Silence inserted **only on speaker change** (0.0–5.0 s) |
| `response_format` | `"wav" \| "mp3" \| "opus" \| "flac" \| "aac" \| "pcm"` | ❌ | `"wav"` | Audio encoding format |
| `speed` | `float` | ❌ | `1.0` | Global speed multiplier (0.25–4.0); see §5.5 for composition |
| `on_error` | `"abort" \| "skip"` | ❌ | `"abort"` | Error handling strategy; see §5.6 for edge cases |

**ScriptSegment Schema:**

```json
{
  "speaker": "alice",
  "voice": "clone:alice_profile",
  "text": "Hello!",
  "speed": 1.2
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `speaker` | `string` | ✅ | Speaker identifier — regex `^[a-zA-Z0-9_-]{1,64}$` |
| `text` | `string` | ✅ | Text to synthesize (1–10,000 chars per segment) |
| `voice` | `string` | ❌ | Voice specification (see §5.2 Voice Resolution). If omitted, inherits from speaker's first definition |
| `speed` | `float` | ❌ | Per-segment speed override — **replaces** global `speed` (not multiplied); see §5.5 |

### 5.2 Voice Resolution

**Voice string formats:**
- `"clone:profile_id"` — Use saved voice profile (profile must exist; validated upfront)
- `"design:male,deep,british accent"` — Voice design attributes (free-text; validated lazily at synthesis time — see §5.7)
- `"alloy"` / `"nova"` / etc. — OpenAI preset names
- `null` or omitted — Inherit from speaker's first appearance in this script

**Resolution order (per segment):**
1. Segment's explicit `voice` field
2. Speaker's first-defined voice in this script (scanning from top)
3. Server default voice (see §5.8)

**Example:**
```json
{
  "script": [
    {"speaker": "alice", "voice": "clone:alice", "text": "First line"},
    {"speaker": "alice", "text": "Second line"},  // ← Inherits "clone:alice"
    {"speaker": "bob",   "voice": "design:male,deep", "text": "Bob's line"},
    {"speaker": "alice", "text": "Third line"}    // ← Still "clone:alice"
  ]
}
```

**Voice defined only mid-script:**
```json
{
  "script": [
    {"speaker": "alice", "text": "Line 1"},       // ← No voice defined yet → server default
    {"speaker": "alice", "voice": "clone:alice", "text": "Line 2"},
    {"speaker": "alice", "text": "Line 3"}        // ← Inherits "clone:alice" from line 2
  ]
}
```
Note: The first segment uses server default, not the later-defined voice. Voice inheritance is forward-only (from first definition, scanning left-to-right).

### 5.3 Response Schema

**Single Track Mode** (`output_format: "single_track"`):
```
HTTP/1.1 200 OK
Content-Type: audio/wav
X-Audio-Duration-S: 4.523
X-Synthesis-Latency-S: 2.341
X-Speakers-Unique: 2
X-Segment-Count: 3
X-Skipped-Segments: 2

<binary audio data>
```

> **Note on `X-Speakers` header (removed in v1.1)**: The v1.0 `X-Speakers: alice,bob,alice,...` header has been removed because with 100 segments the value could exceed the 8KB HTTP header limit. The full speaker order is available in multi-track metadata or can be reconstructed from the segment count and `X-Speakers-Unique`.

**Multi-Track Mode** (`output_format: "multi_track"`):
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
  "tracks": {
    "alice": "<base64_encoded_audio>",
    "bob": "<base64_encoded_audio>"
  },
  "metadata": {
    "total_duration_s": 4.52,
    "speakers_unique": 2,
    "segment_count": 3,
    "skipped_segments": [],
    "segments": [
      {"index": 0, "speaker": "alice", "offset_s": 0.00, "duration_s": 1.80},
      {"index": 1, "speaker": "bob",   "offset_s": 2.30, "duration_s": 2.10},
      {"index": 2, "speaker": "alice", "offset_s": 4.90, "duration_s": 1.60}
    ]
  }
}
```

The `segments` array provides per-segment timestamps that allow clients to reconstruct the conversation timeline, synchronize playback, or align subtitles. `offset_s` is measured from the start of the mixed (single-track) timeline.

> **Multi-Track Limitation**: Each speaker's blob (`tracks.*`) is the **concatenation** of all their segments (gaps omitted). The `segments` metadata is required to reconstruct synchronized playback. If you need synchronized stereo or N-channel output, use `single_track` mode and handle mixing client-side.

### 5.4 Error Responses

**Validation Error (422):**
```json
{"detail": "Script exceeds maximum 100 segments (got 150)"}
```

**Segment-Level Synthesis Error (422 with index):**
```json
{"detail": "Segment 7: synthesis failed — profile 'nonexistent' not found"}
```

**Voice Not Found (422, upfront):**
```json
{"detail": "Segment 2 (speaker 'alice'): profile 'nonexistent_profile' not found"}
```

**Total Timeout (504):**
```json
{"detail": "Script synthesis timed out — total request exceeded 600s"}
```

**Per-Segment Timeout (504 or skip depending on `on_error`):**
```json
{"detail": "Segment 5: synthesis timed out after 120s"}
```

**Partial Failure** (`on_error: "skip"`):
```
HTTP/1.1 200 OK
X-Skipped-Segments: 3,7

<audio with segments 3 and 7 omitted>
```

### 5.5 Speed Composition Rule

There are two `speed` fields: one at request level (`ScriptRequest.speed`) and one at segment level (`ScriptSegment.speed`). They do **not** multiply — the segment value **replaces** the global value:

| Scenario | Effective Speed |
|----------|-----------------|
| `req.speed=1.2`, segment has no `speed` | 1.2 |
| `req.speed=1.2`, `segment.speed=0.8` | **0.8** (segment replaces global) |
| `req.speed` not set, `segment.speed=0.9` | **0.9** |
| Neither set | 1.0 (model default) |

Rationale: multiplication would be surprising and hard to reason about. Override semantics are standard in layered config systems.

### 5.6 `on_error: "skip"` Edge Cases

| Scenario | Behavior |
|----------|---------|
| All segments fail | Return HTTP 422 with detail listing all failures. Never return empty audio. |
| Single-segment script, segment fails | Same as above — return 422, not 200 with empty audio. |
| First segment skipped | Audio starts from next successful segment. No leading pause. |
| Last segment skipped | Audio ends after previous successful segment. No trailing pause. |
| Middle segment skipped | Pause is **not** inserted in place of skipped segment. The audio jumps directly to the next successful segment (which may or may not trigger a speaker-change pause). |
| Skipped segment would have triggered pause | Pause is evaluated based on the **actual synthesized** sequence, not the original script order. If skipped segment was between two Alice segments, no pause is inserted. |
| All segments for one speaker skipped | That speaker produces no audio. `tracks` key for that speaker is absent from multi-track response. |

### 5.7 Validation: Upfront vs. Lazy

Not all voices can be validated before synthesis begins:

| Voice Type | Validation Timing | Notes |
|------------|-------------------|-------|
| `clone:profile_id` | **Upfront** (Step 2, before synthesis) | Profile lookup done eagerly. Returns 422 immediately if any profile not found — includes segment index. |
| `design:attributes` | **Lazy** (at synthesis time, Step 3) | Free-text attributes passed directly to OmniVoice; invalid attributes cause synthesis failure for that segment, reported with segment index. |
| OpenAI preset | **Upfront** (Step 2) | Checked against known preset list. |
| Inherited/default | **N/A** | No validation needed. |

Error reporting always includes the segment index:
```json
{"detail": "Segment 4 (speaker 'alice'): profile 'bad_id' not found"}
```

### 5.8 Default Voice

When no voice is defined for a speaker (neither in the segment nor any prior appearance), the server uses the configured default voice:

```python
# config.py
default_voice: str = Field(
    default="male, middle-aged, moderate pitch, neutral accent",
    description="Default voice description used when no voice is specified"
)
```

> **Note**: `default_voice` is exposed via `Settings` / `config.py` to allow deployers to customize for non-English use cases (e.g., setting a Mandarin or French default voice). This is the only validation-related constant exposed via Settings — API safety limits (`MAX_SCRIPT_SEGMENTS`, etc.) remain hardcoded constants.

### 5.9 Validation Limits

```python
MAX_SCRIPT_SEGMENTS = 100        # Maximum segments per request
MAX_TOTAL_INPUT_CHARS = 50_000   # Total text across all segments
MAX_UNIQUE_SPEAKERS = 10         # Maximum distinct speakers
MAX_SEGMENT_CHARS = 10_000       # Per-segment text limit
```

These are hardcoded constants (not in `Settings`) because they are API contract safety rails, not operational tuning parameters — consistent with how `SpeechRequest.input` uses hardcoded `max_length=10_000`.

---

## 6. Architecture & Implementation

### 6.1 Component Overview

```
omnivoice_server/
├── routers/
│   └── script.py              # NEW - Multi-speaker endpoint
├── services/
│   ├── inference.py           # EXISTING - Reuse for synthesis
│   ├── profiles.py            # EXISTING - Reuse for voice lookup
│   └── script.py              # NEW - ScriptOrchestrator
└── utils/
    └── audio.py               # EXTEND - Add mixing functions
```

### 6.2 Concurrency Policy

**Problem**: With `MAX_CONCURRENT=2`, a 100-segment script calling `synthesize()` 100 times sequentially would hold a semaphore slot for ~8 minutes per call (100 × ~5s), blocking all other `/v1/audio/speech` requests.

**Decision**: The script endpoint uses a **dedicated semaphore** separate from the speech endpoint pool.

```python
# services/script.py
class ScriptOrchestrator:
    def __init__(
        self,
        inference_svc: InferenceService,
        profile_svc: ProfileService,
        script_semaphore: asyncio.Semaphore,  # Dedicated, not shared with speech
    ) -> None:
        ...

# app.py wiring
script_semaphore = asyncio.Semaphore(1)  # 1 concurrent script at a time
orchestrator = ScriptOrchestrator(
    inference_svc=inference_svc,
    profile_svc=profile_svc,
    script_semaphore=script_semaphore,
)
```

**Behavior:**
- The `script_semaphore` is acquired **once for the entire request**, not per-segment
- Each individual `inference_svc.synthesize()` call still competes for the existing `InferenceService` semaphore (per-synthesis slot)
- This means: at most 1 script request runs at a time; script requests and speech requests compete equally for inference slots within that constraint

**Concurrency Budget Summary:**

| Endpoint | Script Semaphore | Inference Semaphore (shared) | Net Behavior |
|----------|-----------------|-----------------------------|--------------|
| `/v1/audio/speech` | Not used | 1 of 2 slots | Up to 2 concurrent speech requests |
| `/v1/audio/script` | 1 of 1 slot | 1 of 2 slots | At most 1 script runs; its segments compete with speech requests |

> **Why 1 concurrent script?** A single 100-segment script saturates the inference pipeline for minutes. Allowing 2 concurrent scripts would starve all speech requests. This is a conservative initial setting — the `Semaphore(1)` limit can be raised via config if the operator increases `MAX_CONCURRENT` hardware capacity.

**503 on script semaphore contention:**
If a second script request arrives while one is running, return `HTTP 503 Service Unavailable`:
```json
{"detail": "Script synthesis at capacity — try again later"}
```
This is a `try_acquire` (non-blocking), not a queue — callers should retry with backoff.

### 6.3 Timeout Contract

The existing `request_timeout_s=120` (default) applies **per-segment synthesis call** inside `asyncio.wait_for()`. The script endpoint adds a **total-request timeout**:

```python
# services/script.py
SCRIPT_TOTAL_TIMEOUT_S = 600  # 10 minutes, hardcoded constant

async def synthesize_script(self, req: ScriptRequest) -> ScriptResult:
    async with asyncio.timeout(SCRIPT_TOTAL_TIMEOUT_S):
        # ... sequential segment synthesis ...
```

| Timeout | Value | Scope | Error |
|---------|-------|-------|-------|
| Per-segment | `cfg.request_timeout_s` (default 120s) | Each `synthesize()` call | 504 or skip per `on_error` |
| Total request | `SCRIPT_TOTAL_TIMEOUT_S = 600s` | Entire script | 504 with `"Script synthesis timed out"` |

**UX Note on Long Scripts**: This endpoint is inherently synchronous (no streaming). With 50+ segments, response times of 2–5 minutes are expected. This is a regression compared to the sentence-level streaming of `/v1/audio/speech`. Phase 2 (see §8.2) will address this with a polling-based job endpoint. In v1.0, callers should set their HTTP client timeout to at least 660s.

### 6.4 Progress Feedback (Phase 2 Roadmap)

> **v1.0 ships without progress feedback** — this is a known limitation (see §3, UX Note).

**Phase 2** will add a job-based endpoint pattern:
- `POST /v1/audio/script` returns `{"job_id": "..."}` immediately
- `GET /v1/audio/script/{job_id}` returns status + partial results:
  ```json
  {"status": "processing", "completed_segments": 12, "total_segments": 50}
  ```
- When complete: `{"status": "done", "audio_url": "/v1/audio/script/{job_id}/audio"}`

> **Why not SSE or `X-Progress` headers?** Response headers are sent once at the start — they cannot be updated mid-stream. SSE is an option but requires significant infra changes. A polling endpoint is simpler to implement and more compatible with existing HTTP clients. Both are deferred to Phase 2.

### 6.5 New Components

**1. ScriptOrchestrator** (`services/script.py`):
```python
class ScriptOrchestrator:
    """Orchestrates multi-speaker synthesis."""

    async def synthesize_script(
        self,
        req: ScriptRequest
    ) -> ScriptResult:
        # 1. Build speaker→voice mapping (upfront validation)
        # 2. Acquire script_semaphore (non-blocking, 503 if contended)
        # 3. Synthesize segments sequentially (with total timeout)
        # 4. Mix audio
        pass
```

**2. Audio Mixing Utilities** (`utils/audio.py`):
```python
def make_silence_tensor(duration_s: float, sample_rate: int = 24000) -> torch.Tensor:
    """Create a silence tensor of given duration."""
    pass

def mix_to_single_track(
    segments: list[tuple[str, torch.Tensor]],  # (speaker, audio)
    pause_s: float,
) -> tuple[torch.Tensor, list[SegmentTimestamp]]:
    """Concatenate segments with speaker-change pauses.
    Returns (mixed_audio, per_segment_timestamps)."""
    pass

def group_by_speaker(
    segments: list[tuple[str, torch.Tensor]],
) -> dict[str, torch.Tensor]:
    """Concatenate each speaker's segments."""
    pass
```

**3. Script Router** (`routers/script.py`):
```python
@router.post("/audio/script")
async def create_script(
    body: ScriptRequest,
    orchestrator: ScriptOrchestrator = Depends(...)
) -> Response:
    # Validate → Orchestrate → Return
    pass
```

### 6.6 Synthesis Flow

```
┌─────────────────────────────────────────────────────────┐
│ 1. Validate Request (Pydantic)                          │
│    - Check segment count ≤ 100                          │
│    - Check total chars ≤ 50K, per-segment ≤ 10K         │
│    - Validate speaker ID format (regex)                 │
│    - Check unique speaker count ≤ 10                    │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│ 2. Resolve & Upfront-Validate Voices                    │
│    - Build speaker→voice map (first-definition rule)    │
│    - Lookup profiles for "clone:*" → 422 if not found   │
│    - Validate OpenAI presets against known list         │
│    - "design:" voices: deferred (validated at synthesis)│
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│ 3. Acquire script_semaphore (non-blocking)              │
│    - If already held → 503 immediately                  │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│ 4. Synthesize Segments (under total timeout = 600s)     │
│    - For each segment:                                  │
│      • Build SynthesisRequest with resolved voice       │
│      • Apply speed (segment overrides global)           │
│      • Call inference_svc.synthesize() — acquires       │
│        shared inference semaphore per call              │
│      • Per-segment timeout = cfg.request_timeout_s      │
│    - On error: abort (raise) or skip (record + continue)│
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│ 5. Insert Pauses + Compute Timestamps                   │
│    - Pause inserted when segment[i].speaker ≠           │
│      segment[i-1].speaker (after skipped-segment        │
│      resolution — compare actual synthesized neighbors) │
│    - pause_between_speakers=0.0 → hard cut (no silence) │
│    - Accumulate per-segment offset_s                    │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│ 6. Mix Audio                                            │
│    - single_track: concat all tensors → binary          │
│    - multi_track: group by speaker + segment timestamps │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│ 7. Format Conversion + Release semaphore                │
│    - Convert to requested format (mp3/opus/pcm/etc)     │
│    - Emit metrics                                       │
│    - Return audio + metadata headers                    │
└─────────────────────────────────────────────────────────┘
```

### 6.7 Memory Budget

**Analysis** (for 100-segment worst-case):
```
Assumptions:
  - 100 segments × 15s average audio each
  - 24,000 samples/s × 4 bytes (float32)
  - All tensors held simultaneously before mixing

Peak memory:
  100 × 15 × 24,000 × 4 = 144 MB (tensors only)
  + format conversion overhead (pydub AudioSegment copy) ≈ 60–80 MB
  Total worst-case: ~220 MB
```

**Target**: The v1.0 spec's "< 100 MB" target is incorrect. Realistic peak is ~220 MB for the pathological case.

**Enforcement mechanism**: Instead of trying to fit 100 segments in memory at once, cap total estimated audio duration:

```python
MAX_TOTAL_AUDIO_DURATION_S = 600  # 10 minutes of synthesized audio
```

This limit is estimated upfront (pessimistically, using char count / average speaking rate ~15 chars/s) before synthesis begins:

```python
estimated_duration_s = sum(len(seg.text) for seg in req.script) / 15.0
if estimated_duration_s > MAX_TOTAL_AUDIO_DURATION_S:
    raise HTTPException(422, f"Estimated audio duration {estimated_duration_s:.0f}s exceeds limit 600s")
```

Actual memory at that limit:
```
600s × 24,000 × 4 bytes = 57.6 MB tensors
```

This fits within a comfortable budget with room for overhead.

**Note**: Streaming tensor processing (process-and-discard each segment after mixing) is the long-term solution but requires architectural changes deferred to Phase 2/3.

### 6.8 Observability

The script endpoint emits metrics to an **additional** `ScriptMetricsService` instance (or a separate tag/prefix on the existing `MetricsService`), not mixed with per-request speech metrics:

| Metric | Method | Description |
|--------|--------|-------------|
| `script_request_latency_s` | `record_success(latency_s)` | Wall-clock time for entire script request |
| `script_request_error` | `record_error()` | Request-level errors (validation, timeout, all-skip) |
| `script_request_timeout` | `record_timeout()` | Requests that exceeded `SCRIPT_TOTAL_TIMEOUT_S` |
| `script_segments_synthesized` | Custom counter | Total segments successfully synthesized (across all requests) |
| `script_segments_skipped` | Custom counter | Total segments skipped via `on_error: "skip"` |
| `script_voice_resolution_failures` | Custom counter | Upfront voice resolution failures (profile not found, etc.) |

**Implementation note**: `MetricsService` is currently a flat in-memory counter. For the new metrics, we either:
1. Instantiate a second `MetricsService` labeled `"script"` and expose it at `/metrics` under a `script_*` namespace, or
2. Extend `MetricsService` with a `namespace` parameter.

Prefer option 1 (separate instance) to avoid touching existing `MetricsService` interface.

---

## 7. Design Decisions & Rationale

### 7.1 Post-Processing vs Model-Level

**Decision**: Use post-processing approach (synthesize segments → mix audio)

**Rationale**:
- OmniVoice model does NOT support native multi-speaker (confirmed via code analysis)
- Post-processing works TODAY without model changes
- Provides full control over pause timing and mixing
- Can be upgraded to model-level if OmniVoice adds support in future

**Alternative Considered**: Wait for OmniVoice native support
- **Rejected**: No timeline for native support, user need is immediate

### 7.2 Fail-Fast Error Handling

**Decision**: Default `on_error: "abort"` with optional `"skip"` mode

**Rationale**:
- Consistent with existing codebase pattern (all endpoints fail-fast)
- Partial audio without error indication is dangerous for production use
- `"skip"` mode available for fault-tolerant scenarios

**Evidence**: `speech.py` streaming implementation aborts on first error (lines 264-271)

### 7.3 Voice Inheritance

**Decision**: Inherit voice from speaker's first appearance (forward-only scan)

**Rationale**:
- Reduces boilerplate (define voice once per speaker)
- Matches mental model of PlayHT API
- Better developer experience

**Example**: Alice appears 10 times → define voice once, not 10 times

### 7.4 No Strategy Pattern (Yet)

**Decision**: Implement simple `ScriptOrchestrator` class, defer abstraction

**Rationale**:
- YAGNI principle — OmniVoice won't add native support soon
- Codebase doesn't use strategy pattern elsewhere
- Premature abstraction adds complexity without benefit
- Easy to refactor later if needed

### 7.5 Validation Limits Are Hardcoded Constants

**Decision**: Limits such as `MAX_SCRIPT_SEGMENTS=100` are hardcoded constants, not in `Settings`

**Rationale**:
- Limits are API contract, not operational tuning parameters
- Consistent with existing pattern (`SpeechRequest.input` has hardcoded `max_length=10_000`)
- Exception: `default_voice` is in `Settings` because deployers legitimately need to change it for non-English deployments

### 7.6 Dedicated Script Semaphore

**Decision**: `script_semaphore = asyncio.Semaphore(1)` — separate from speech semaphore

**Rationale**:
- Prevents a single expensive script from monopolizing the shared inference pool
- 503 on contention (non-queuing) keeps the server predictably responsive
- 1 concurrent script is conservative and correct for initial release

### 7.7 Speed Override (Not Multiply)

**Decision**: `segment.speed` replaces `req.speed` rather than multiplying

**Rationale**:
- Multiplication is unintuitive: `req.speed=2.0`, `segment.speed=0.5` → effective 1.0 is surprising
- Override semantics are standard in layered config (CSS cascade, environment variables)
- Easier to reason about and test

---

## 8. Implementation Plan

### 8.1 Phase 1: Core Implementation (4-5 days)

**Task 1.1**: Audio mixing utilities (1 day)
- Add `make_silence_tensor()` to `utils/audio.py`
- Add `mix_to_single_track()` with pause insertion + timestamp accumulation
- Add `group_by_speaker()` for multi-track
- Unit tests for pause insertion, mixing, and timestamp calculation

**Task 1.2**: ScriptOrchestrator service (2 days)
- Create `services/script.py`
- Implement voice resolution logic (upfront + lazy)
- Implement segment synthesis orchestration with dedicated semaphore
- Error handling per `on_error` strategy including all edge cases (§5.6)
- Memory budget enforcement (estimated duration check)

**Task 1.3**: Script router (1-2 days)
- Create `routers/script.py`
- Define `ScriptRequest` / `ScriptSegment` Pydantic models
- Implement validation (limits, speaker ID regex, voice strings)
- Wire up to ScriptOrchestrator
- Register in `app.py`

**Task 1.4**: Observability (0.5 days)
- Create second `MetricsService` instance labeled for script metrics
- Emit metrics at all success/error/timeout paths
- Update `/metrics` endpoint to include `script_*` namespace

**Task 1.5**: OpenAPI / Swagger Update (0.5 days)
- Ensure FastAPI auto-generates correct schema for `ScriptRequest` and `ScriptSegment`
- Add endpoint description and example in route docstring
- Verify `/docs` and `/openapi.json` reflect new endpoint

### 8.2 Phase 2: Progress Feedback (2 days, follow-up release)

**Task 2.1**: Job-based endpoint
- `POST /v1/audio/script` optionally returns `{"job_id": "..."}` (controlled by `async: true` flag)
- `GET /v1/audio/script/{job_id}` — polling status endpoint
- Background task queue (asyncio, no external deps)

### 8.3 Phase 3: Testing & Polish (2-3 days)

**Task 3.1**: Integration tests
- Test single_track output
- Test multi_track output with timestamp verification
- Test error handling (abort vs skip, all edge cases)
- Test voice resolution (clone/design/preset/inherit)
- Test semaphore contention → 503
- Test total timeout → 504

**Task 3.2**: Manual QA
- Test with real audiobook script (50+ segments)
- Test with podcast dialogue (2-3 speakers)
- Verify pause timing
- Verify audio quality

**Task 3.3**: Documentation
- Update API reference docs
- Add usage examples (audiobook, podcast)
- Update README

---

## 9. Testing & Validation

### 9.1 Test Cases

**Functional Tests:**
1. Single speaker, 3 segments → verify concatenation
2. Two speakers alternating → verify pause insertion at speaker changes only
3. Same speaker 3× consecutive → verify **no** intra-speaker pause
4. Voice inheritance → verify same voice used for all speaker appearances
5. Voice defined mid-script → verify first segment uses default, rest inherit
6. Clone voice → verify profile lookup (upfront)
7. Clone voice, profile missing → 422 with segment index
8. Design voice → accepted; invalid attributes fail at synthesis with segment index
9. OpenAI preset → verify preset mapping
10. Multi-track output → verify JSON structure + segment timestamps
11. Error: nonexistent profile → 422 before synthesis starts
12. Error: segment timeout → 504 (`abort`) or skip + continue (`skip`)
13. All segments fail (`skip`) → 422 (not 200 empty)
14. Single segment fails (`skip`) → 422
15. Validation: 101 segments → 422
16. Validation: total chars > 50K → 422
17. Script semaphore contention → 503
18. `speed` override: global 1.5, segment 0.8 → effective 0.8
19. `speed` override: global 1.5, segment absent → effective 1.5
20. `response_format: "pcm"` → verify pcm binary returned

**Performance Tests:**
1. 10 segments, 2 speakers → latency < 30s
2. 50 segments, 5 speakers → latency < 5 minutes
3. 100 segments, estimated duration > 600s → 422 (duration limit)

### 9.2 Success Criteria

- ✅ All functional tests pass
- ✅ API returns valid audio for all test cases
- ✅ Error responses include segment index where applicable
- ✅ Semaphore contention returns 503 (not hang)
- ✅ Documentation complete and accurate
- ✅ OpenAPI schema correct and visible at `/docs`
- ✅ Script metrics visible at `/metrics`

---

## 10. Future Considerations

### 10.1 If OmniVoice Adds Native Multi-Speaker

**Scenario**: OmniVoice adds `voice2`, `turn_prefix` parameters (like PlayHT)

**Migration Path**:
1. Add capability detection in `ScriptOrchestrator`
2. Implement native synthesis path
3. Fallback to post-processing if native fails
4. Expose `strategy: "auto" | "native" | "postprocess"` in API

**No breaking changes** — existing API continues to work.

### 10.2 Potential Enhancements

**Job-Based / Async Output (Phase 2):**
- Return job ID immediately, poll for completion
- Enables progress feedback (`completed_segments / total_segments`)
- Webhook notification when done
- Required for scripts > 50 segments to be usable in production

**Parallel Synthesis (Phase 3):**
- Synthesize non-adjacent same-speaker segments concurrently
- Requires careful deadlock analysis with `MAX_CONCURRENT=2` semaphore:
  - If script_semaphore allows 1 script, and that script spawns N parallel segments, each competing for 1 of 2 inference slots → no deadlock (N segments queue but don't block each other)
  - Risk: 1 script can monopolize all inference slots if N ≥ MAX_CONCURRENT
  - Mitigation: cap parallel synthesis at `max(1, MAX_CONCURRENT - 1)` to leave at least 1 slot for speech requests
- Benchmark latency improvement before implementing

**SSML Input Support:**
```xml
<speak>
  <voice name="alice">Hello!</voice>
  <voice name="bob">Hi there!</voice>
</speak>
```
Parse SSML → convert to script format → synthesize

**Per-Segment Language:**
- Add `language` field to `ScriptSegment` for multilingual scripts
- OmniVoice supports 600+ languages natively
- Currently unsupported — callers can work around via `voice: "design:..., [language] accent"`

**Streaming Output:**
- Stream audio chunks as segments complete (SSE or chunked transfer)
- Reduces time-to-first-audio for long scripts
- Significant infra change — deferred to Phase 2+

**Idempotency Key:**
- `Idempotency-Key: <uuid>` header to deduplicate retries
- If script synthesis succeeds but network fails, retry with same key returns cached result
- Requires result cache (filesystem or Redis) — deferred to Phase 2

---

## 11. Appendix

### 11.1 Market Research Summary

**Commercial APIs:**
- PlayHT PlayDialog: Native model-level, `voice`/`voice2` params
- Azure TTS: SSML `<voice>` tags
- ElevenLabs: No native multi-speaker

**Open-Source:**
- Coqui TTS: Speaker IDs for multi-speaker models
- Piper TTS: Single-speaker only

**Conclusion**: Post-processing approach is standard for self-hosted TTS.

### 11.2 File References

**Existing Files to Modify:**
- `omnivoice_server/utils/audio.py` — Add mixing functions
- `omnivoice_server/app.py` — Register script router + create `script_semaphore`
- `omnivoice_server/config.py` — Add `default_voice` field to `Settings`
- `omnivoice_server/routers/health.py` — Expose `script_*` metrics at `/metrics`

**New Files to Create:**
- `omnivoice_server/routers/script.py` — Script endpoint
- `omnivoice_server/services/script.py` — ScriptOrchestrator

**Files Analyzed:**
- `OmniVoice/omnivoice/models/omnivoice.py` — Model capabilities (lines 458-527)
- `omnivoice_server/routers/speech.py` — Error handling patterns
- `omnivoice_server/services/inference.py` — Synthesis service, semaphore (lines 157-179)
- `omnivoice_server/services/metrics.py` — MetricsService interface (lines 11-49)
- `omnivoice_server/app.py` — Auth middleware (lines 99-114)
- `omnivoice_server/config.py` — Settings, `max_concurrent`, `request_timeout_s`

### 11.3 Glossary

- **Script**: Ordered list of speaker segments
- **Segment**: Single speaker's text in the script
- **Voice Resolution**: Process of determining which voice to use for a speaker
- **Post-Processing**: Synthesizing segments separately then mixing audio
- **Model-Level**: Native multi-speaker support in the TTS model itself
- **Script Semaphore**: Dedicated `asyncio.Semaphore(1)` for the script endpoint — separate from the shared inference semaphore
- **Upfront Validation**: Validation performed before synthesis begins (e.g., profile lookup)
- **Lazy Validation**: Validation that only fails at synthesis time (e.g., `design:` attribute errors)

---

**End of Document**

---

## Review Checklist (v1.1)

- [x] Background section accurately describes OmniVoice capabilities
- [x] Problem statement clearly articulates user need
- [x] API design is complete and unambiguous
- [x] **C1** Concurrency policy defined: dedicated script semaphore, 503 on contention
- [x] **C2** Multi-track per-segment timestamps documented; synchronization limitation explicit
- [x] **C3** Timeout contract clarified (per-segment vs total); Phase 2 job endpoint roadmapped
- [x] **C4** Auth model documented: global middleware inheritance, no per-user rate limit
- [x] **M1** Speed composition rule defined: segment replaces global (not multiply)
- [x] **M2** `pcm` format restored to supported list
- [x] **M3** Upfront vs lazy validation documented; segment index in all error responses
- [x] **M4** `on_error: "skip"` edge cases fully specified
- [x] **M5** Memory budget analysis corrected; `MAX_TOTAL_AUDIO_DURATION_S` enforcement
- [x] **M6** Metrics defined: 6 script-specific metrics, separate MetricsService instance
- [x] **M7** Pause trigger condition explicit: `segment[i].speaker ≠ segment[i-1].speaker`
- [x] **m1** `default_voice` exposed via `Settings` for deployer customization
- [x] **m2** OpenAPI update added to Phase 1 task list (Task 1.5)
- [x] **m3** `X-Speakers` header removed; replaced by `X-Speakers-Unique` only
- [x] **m4** Idempotency key documented in Future Considerations (Phase 2)
- [x] **m5** Phase 3 parallel synthesis deadlock analysis added to §10.2
- [x] **m6** Per-segment language documented in Future Considerations
- [x] Design decisions have clear rationale
- [x] Implementation plan is realistic and detailed
- [x] Test cases cover all critical scenarios including new edge cases

**Next Steps**: Final review → approve for implementation.
