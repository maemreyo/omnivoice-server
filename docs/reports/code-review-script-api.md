# Code Review: Multi-Speaker Script API Implementation
**Patch**: `script-api-code-only.patch`  
**Review date**: 2026-04-18  
**Files changed**: `routers/script.py` (new), `services/script.py` (modified), `utils/audio.py` (modified), `app.py` (modified), `tests/test_script.py` (new)

---

## Overall Assessment

Implementation is **solid and largely correct** — the spec was faithfully translated to code. Test coverage is good, the audio mixing utilities are clean, and the observability wiring is well done. However there are **2 correctness bugs**, **1 critical architecture mistake**, and **several rough edges** worth addressing before merge.

---

## Bugs

---

### BUG-1 🔴 — Multi-Track `total_duration_s` Is Computed Wrong

**File**: `routers/script.py`, line 1374

```python
# WRONG: adds (n-1) pauses regardless of how many speaker changes actually occurred
total_duration_s = sum(ts.duration_s for ts in timestamps) + body.pause_between_speakers * (
    len(timestamps) - 1
)
```

This formula assumes there's a pause between **every pair of consecutive segments**, but pauses are only inserted on **speaker changes**. A script with Alice speaking 10 times in a row would report a duration inflated by 9 pauses that don't exist.

`mix_to_single_track` already returns the **correct** timeline via the timestamps list and knows exactly where pauses were inserted. Use the actual accumulated offset instead:

```python
# CORRECT: final segment's offset + its duration = true total
if timestamps:
    last = timestamps[-1]
    total_duration_s = last.offset_s + last.duration_s
else:
    total_duration_s = 0.0
```

---

### BUG-2 🔴 — Profile Looked Up Twice Per Segment

**File**: `services/script.py`, `_resolve_voices` + `_build_synthesis_request`

`_resolve_voices` looks up the profile upfront to validate it exists — good. But then `_build_synthesis_request` (now async) calls `self._profiles.get_ref_audio_path(profile_id)` **again** for every segment. For a 50-segment script where all segments use `clone:alice`, this means **51 profile lookups** (1 upfront + 50 per-segment).

```python
# _build_synthesis_request — redundant second lookup
ref_audio_path = await self._profiles.get_ref_audio_path(profile_id)  # <-- already done in _resolve_voices
```

**Fix**: The upfront resolution should return a map of `speaker → SynthesisRequest` (or `speaker → ref_audio_path`), not just `speaker → voice_string`. Pass the resolved path through, not the raw voice string.

---

### BUG-3 🟠 — NaN Test Has Wrong Assertion

**File**: `tests/test_script.py`, `test_script_malformed_tensor_handling`

```python
with pytest.raises(ValueError, match="NaN or Inf"):
    client.post(...)
```

`client.post()` is an HTTP call — it returns a `Response` object, it never raises `ValueError`. If the server catches the `ValueError` internally and returns a 500, this test silently passes for the wrong reason (the `pytest.raises` context never sees the ValueError). If the server doesn't catch it and crashes the test process, that's a different bug.

**Fix**: Assert on the response status code instead:
```python
resp = client.post("/v1/audio/script", json={...})
assert resp.status_code == 500
```

Or, if NaN should be handled gracefully, assert 422.

---

## Architecture Issues

---

### ARCH-1 🔴 — Wrong Primitive: `threading.Lock` in Async Code

**File**: `services/script.py`, lines 1447–1448, 1631–1636, 1784–1786

```python
self._slot_lock = threading.Lock()
self._slot_occupied = False
```

The original `asyncio.Semaphore(1)` was removed and replaced with a `threading.Lock` + bool flag. This works by accident (the event loop is single-threaded so the critical section without an `await` is effectively atomic), but it's conceptually wrong and will confuse anyone reading the code. `threading.Lock` is for multi-threaded code. The correct primitive here is either:

```python
# Option A: back to the original
self._semaphore = asyncio.Semaphore(1)
if not self._semaphore.locked():  # non-blocking check
    ...

# Option B: asyncio.Lock (more explicit)
self._lock = asyncio.Lock()
if self._lock.locked():
    raise HTTPException(503, ...)
async with self._lock:
    ...
```

Note: `asyncio.Semaphore.locked()` and `asyncio.Lock.locked()` are non-blocking checks — exactly what the original spec called for (fail-fast 503, not queue).

---

### ARCH-2 🟡 — `_ScriptAdapterRequest` Is an Unnecessary Layer

**File**: `routers/script.py`, lines 1278–1287

```python
@dataclass
class _ScriptAdapterRequest:
    segments: list       # untyped
    default_voice: str | None
    speed: float
    on_error: str        # no Literal type
    insert_pause_ms: int
```

This dataclass exists solely to bridge `ScriptRequest` (Pydantic) to `ScriptOrchestrator`. It loses all type safety (untyped `list`, `str` instead of `Literal["abort","skip"]`) and introduces a translation step where float → int conversion for `insert_pause_ms` also loses information.

The orchestrator should accept `ScriptRequest` directly, or define its own typed interface. Having two parallel representations of the same data is a maintenance trap.

---

### ARCH-3 🟡 — Dead Code: `except asyncio.TimeoutError: raise`

**File**: `services/script.py`, lines 1749–1750

```python
try:
    result = await asyncio.wait_for(self._synthesize_segments(...), timeout=SCRIPT_TOTAL_TIMEOUT_S)
except asyncio.TimeoutError:
    raise  # ← dead code
```

Catching an exception and immediately re-raising it is a no-op — the exception propagates identically without this block. It does NOT protect against the outer `except Exception as e:` clause because `except` clauses are tried in order; the outer handler already has `except asyncio.TimeoutError` before `except Exception`. Remove this block.

---

## Minor Issues

---

### M1 — `pause_between_speakers` Float → Int → Float Roundtrip

**File**: `routers/script.py`, line 1312

```python
insert_pause_ms=int(body.pause_between_speakers * 1000)
```

This converts float seconds → int milliseconds → float seconds later (`req.insert_pause_ms / 1000.0`). For audio, ms precision is fine, but the integer representation is an unnecessary intermediary. Passing the float directly and naming it `pause_s` (as the audio utilities already expect) would be cleaner and remove the back-conversion in the memory budget estimator.

---

### M2 — `response_format` Silently Ignored in Multi-Track Mode

**File**: `routers/script.py`, line 1365

```python
wav_bytes = tensor_to_wav_bytes(tensor)  # always WAV, regardless of response_format
```

Single-track mode respects `response_format`. Multi-track mode ignores it and always returns WAV-encoded base64 blobs. This asymmetry is undocumented. If `response_format: "mp3"` is passed with `output_format: "multi_track"`, the caller silently gets WAV blobs.

Either apply `tensors_to_formatted_bytes` in multi-track mode too, or document the limitation explicitly in the API spec and return a 422 if `multi_track` is combined with a non-WAV format.

---

### M3 — `mix_to_single_track` Called Twice in Multi-Track Path

**File**: `routers/script.py`, lines 1369–1371

```python
# multi_track path: called ONLY to get timestamps
_, timestamps = mix_to_single_track(segments_with_tensors, pause_s=body.pause_between_speakers)
```

In multi-track mode, `mix_to_single_track` is called to compute timestamps but its output tensor is discarded. The function still concatenates all tensors into a single mixed audio just to throw it away. For a 100-segment script, this is a significant waste of compute and memory.

**Fix**: Extract timestamp computation into a separate utility function that doesn't do the audio concatenation. Or restructure so timestamp computation is a first-class output of `_synthesize_segments` (where it naturally accumulates anyway).

---

### M4 — `_build_synthesis_request` Validates OpenAI Presets at Synthesis Time

**File**: `services/script.py`, line 1523

```python
if not instruct:
    raise ValueError(f"Invalid OpenAI preset: {preset_name}")
```

The spec (§5.7) says OpenAI presets are validated **upfront** in Step 2 (`_resolve_voices`). But the `ValueError` is raised inside `_build_synthesis_request`, which is called per-segment in Step 3. If segment #99 uses an invalid preset, 98 segments are synthesized before the error surfaces — exactly the problem the spec was trying to avoid for `clone:` voices.

**Fix**: Move OpenAI preset validation into `_resolve_voices` alongside the `clone:` profile checks.

---

### M5 — `segments` Tuple Is Redundant

**File**: `services/script.py`, around line 1726

```python
segments = [(seg.speaker, seg) for seg in segments]
# then later:
for i, (speaker, segment) in enumerate(segments):
    voice = speaker_voices[speaker]
```

The tuple `(seg.speaker, seg)` is redundant because `speaker` is already accessible as `segment.speaker`. This was likely a refactoring artifact. Simplify to iterate directly over `segments` and use `seg.speaker`.

---

## What Could Be More Powerful

Beyond correctness — here are ideas that would make this feature significantly more interesting and differentiated.

---

### IDEA-1 ⭐ — Subtitle / SRT Export Alongside Audio

The multi-track metadata already computes `offset_s` and `duration_s` per segment. The server is now one step away from generating subtitle files:

```json
// Request addition:
"subtitle_format": "srt" | "vtt" | null
```

```
// Response header:
X-Subtitle: <base64-encoded SRT>
```

The text is already in the request; the timestamps are computed during mixing. This takes ~20 lines to implement and would make the endpoint uniquely useful for video production workflows. No other self-hosted TTS does this out of the box.

---

### IDEA-2 ⭐ — Auto Non-Verbal Injection from Text Signals

OmniVoice supports `[laughter]`, `[sigh]`, `[question-en]` etc. The server could automatically inject these based on simple text heuristics before synthesis:

```python
def enrich_text(text: str) -> str:
    if re.search(r'\bhaha\b|lol|heh', text, re.I):
        text = text + " [laughter]"
    if text.endswith("..."):
        text = text.replace("...", "... [sigh]")
    return text
```

Expose this as `auto_nonverbals: bool = False`. When enabled, the engine becomes dramatically more expressive with zero effort from the caller. Podcast and game dialogue use cases would benefit enormously.

---

### IDEA-3 ⭐ — Per-Segment Emotion / Direction Hints

```json
{
  "speaker": "alice",
  "text": "I can't believe it.",
  "voice": "clone:alice",
  "direction": "shocked, quiet"
}
```

The `direction` string gets prepended to the voice design instruction at synthesis time: `"clone:alice [shocked, quiet]"`. If the underlying model supports design attributes on top of clone prompts, this unlocks expressive dialogue. If not, it degrades gracefully (ignored). This matches the mental model of a film script's stage directions.

---

### IDEA-4 ⭐ — Smart Pause Inference from Punctuation

Fixed `pause_between_speakers=0.5s` for all speaker changes produces robotic timing. Real conversations have dynamic pacing:

```python
def infer_pause(prev_text: str, pause_base: float) -> float:
    if prev_text.rstrip().endswith("?"):
        return pause_base * 0.7   # quick response to a question
    if prev_text.rstrip().endswith("..."):
        return pause_base * 1.8   # hesitation, longer gap
    if prev_text.rstrip().endswith("!"):
        return pause_base * 0.5   # excited, fast reply
    return pause_base
```

Expose as `smart_pauses: bool = false`. When enabled, pauses adapt to the natural rhythm of the dialogue. Very low implementation cost, high perceptual quality gain.

---

### IDEA-5 ⭐ — Streaming Output (Per-Segment Chunks)

The current endpoint sends nothing until all segments are synthesized. The alternative: stream each segment as WAV chunk as soon as it completes synthesis, using chunked transfer encoding. Callers get the first segment of audio in 3-5 seconds instead of 3-5 minutes.

```
HTTP/1.1 200 OK
Transfer-Encoding: chunked
Content-Type: audio/wav

<WAV header>
<chunk: alice segment 1>
<chunk: silence>
<chunk: bob segment 2>
...
```

This requires restructuring `_synthesize_segments` to yield tensors instead of collecting them, but it would be the single most impactful UX improvement. Time-to-first-audio goes from minutes to seconds.

---

### IDEA-6 — Background Audio / Ambience Track

```json
{
  "script": [...],
  "background": {
    "url": "https://example.com/cafe-ambience.mp3",
    "volume": 0.2
  }
}
```

Mix a background audio track under the synthesized dialogue. The pydub infrastructure is already in place. This would make the endpoint genuinely useful for podcast and game dialogue production without any additional tooling. Implement as optional; if `background` is null, behavior is identical to current.

---

## Summary Table

| ID | Severity | Type | Description |
|----|----------|------|-------------|
| BUG-1 | 🔴 Bug | Correctness | Multi-track `total_duration_s` wrong (overcounts pauses) |
| BUG-2 | 🔴 Bug | Performance | Profile looked up twice per segment |
| BUG-3 | 🟠 Bug | Test | NaN test asserts wrong thing (`ValueError` vs HTTP 500) |
| ARCH-1 | 🔴 Architecture | Correctness | `threading.Lock` in async code — should be `asyncio.Lock` |
| ARCH-2 | 🟡 Architecture | Design | `_ScriptAdapterRequest` unnecessary, loses type safety |
| ARCH-3 | 🟡 Architecture | Dead code | `except asyncio.TimeoutError: raise` is a no-op |
| M1 | 🟡 Minor | Design | Float → int → float roundtrip for pause_ms |
| M2 | 🟡 Minor | Correctness | `response_format` silently ignored in multi-track |
| M3 | 🟡 Minor | Performance | `mix_to_single_track` called twice; output discarded |
| M4 | 🟠 Minor | Correctness | OpenAI preset validated lazily, not upfront (violates spec §5.7) |
| M5 | 🟡 Minor | Cleanup | Redundant tuple wrapping in `_synthesize_segments` |

**Must fix before merge**: BUG-1, BUG-2, ARCH-1, M4  
**Should fix in follow-up**: BUG-3, ARCH-2, ARCH-3, M2, M3  
**Consider**: IDEA-1 (subtitles), IDEA-2 (auto non-verbals), IDEA-4 (smart pauses)

---

*End of Review*
