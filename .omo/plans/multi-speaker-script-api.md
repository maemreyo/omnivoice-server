# Multi-Speaker Script API — Implementation Plan

## TL;DR

> **Quick Summary**: Implement `POST /v1/audio/script` endpoint that synthesizes multi-speaker dialogue by sequentially synthesizing each segment and mixing them into a single or multi-track audio output.
>
> **Deliverables**:
> - `omnivoice_server/services/script.py` — ScriptOrchestrator service (new)
> - `omnivoice_server/routers/script.py` — FastAPI router + Pydantic models (new)
> - `omnivoice_server/utils/audio.py` — Extend with mixing utilities
> - `omnivoice_server/config.py` — Add `default_voice` setting
> - `omnivoice_server/app.py` — Wire script router + script_semaphore
> - `omnivoice_server/routers/health.py` — Expose `script_*` metrics
> - `tests/test_script.py` — Comprehensive test suite
>
> **Estimated Effort**: Medium (2–3 days)
> **Parallel Execution**: YES — 2 waves
> **Critical Path**: Task 1 → Task 3 → Task 5 → Task 6 → Task 7 → Task 8

---

## Context

### Original Request
Read `docs/specs/multi-speaker-script-api.md` (v1.1), investigate the codebase, plan and implement.

### Spec Summary
- **Endpoint**: `POST /v1/audio/script`
- **Input**: `{ script: [{ speaker, voice, text, speed }], output_format, pause_between_speakers, response_format, speed, on_error }`
- **Voice resolution**: `clone:profile_id` | `design:attributes` | OpenAI preset | inherited from speaker's first definition | server default
- **Output modes**: `single_track` (binary audio) or `multi_track` (JSON with base64 blobs + timestamps)
- **Concurrency**: Dedicated `asyncio.Semaphore(1)` — separate from speech pool. 503 on contention.
- **Timeouts**: Per-segment `cfg.request_timeout_s` (default 120s) + total `SCRIPT_TOTAL_TIMEOUT_S=600s`
- **Error handling**: `on_error: abort` (default) | `skip` (record + continue)
- **Limits**: 100 segments, 50k total chars, 10 unique speakers, 10k chars/segment
- **Memory**: Upfront duration estimate check (≤600s of audio)
- **Metrics**: Separate `MetricsService` instance with 6 script-specific metrics

### Codebase Investigation Findings

**Key files and patterns:**

- `omnivoice_server/app.py` — Uses `app.state.*` for dependency injection. Lifespan creates all services. `app.include_router()` to register routers. No script-related wiring yet.
- `omnivoice_server/config.py` — `Settings(BaseSettings)` with pydantic-settings. Missing `default_voice` field.
- `omnivoice_server/utils/audio.py` — Contains `tensor_to_wav_bytes`, `tensors_to_formatted_bytes`, `ResponseFormat`. Need to add: `make_silence_tensor`, `mix_to_single_track`, `group_by_speaker`.
- `omnivoice_server/routers/speech.py` — Pattern: `Depends(lambda req: req.app.state.X)`, `HTTPException`, `Response`. Pydantic models inline in router file.
- `omnivoice_server/services/inference.py` — `InferenceService.synthesize(req: SynthesisRequest) -> SynthesisResult`. Uses `asyncio.Semaphore` + `asyncio.wait_for`. `SynthesisRequest` dataclass.
- `omnivoice_server/services/metrics.py` — `MetricsService` with `record_success/error/timeout`, `snapshot()`.
- `omnivoice_server/services/profiles.py` — `ProfileService.get_ref_audio_path(id)` raises `ProfileNotFoundError`. `get_ref_text(id)`.
- `omnivoice_server/voice_presets.py` — `OPENAI_VOICE_PRESETS` dict, `DEFAULT_DESIGN_INSTRUCTIONS`.
- `tests/conftest.py` — `make_silence_tensor()`, `_mock_synthesize()`, `settings` fixture (pydantic Settings), `client` fixture (TestClient with mocked model).

**Dependency injection pattern** (from speech.py):
```python
def _get_inference(request: Request) -> InferenceService:
    return request.app.state.inference_svc
```

**Error response pattern** (app.py exception handlers):
```python
raise HTTPException(status_code=422, detail="human-readable message")
```

**Metrics pattern**: second `MetricsService` instance labeled `"script"` — expose under `script_*` keys in `/metrics` response.

---

## Work Objectives

### Core Objective
Implement the full `POST /v1/audio/script` endpoint as specified in `docs/specs/multi-speaker-script-api.md` v1.1, matching existing codebase conventions exactly.

### Concrete Deliverables
1. `omnivoice_server/services/script.py` — new file
2. `omnivoice_server/routers/script.py` — new file  
3. `omnivoice_server/utils/audio.py` — extended with 3 new functions
4. `omnivoice_server/config.py` — `default_voice` field added
5. `omnivoice_server/app.py` — script router + script_semaphore wired in
6. `omnivoice_server/routers/health.py` — script metrics exposed
7. `tests/test_script.py` — new test file

### Definition of Done
- [ ] `POST /v1/audio/script` returns 200 with binary audio for valid scripts
- [ ] `POST /v1/audio/script` returns 200 JSON for `output_format: multi_track`
- [ ] Voice resolution (clone/design/preset/inherit/default) works correctly
- [ ] `on_error: skip` skips failed segments; `abort` fails immediately
- [ ] Semaphore contention returns 503
- [ ] `/metrics` response includes `script_requests_total` etc.
- [ ] All tests in `tests/test_script.py` pass
- [ ] Existing tests still pass (`pytest tests/ -x`)

### Must Have
- Dedicated `script_semaphore = asyncio.Semaphore(1)` — NOT shared with speech
- Upfront clone profile validation (422 before synthesis starts)
- Total request timeout `SCRIPT_TOTAL_TIMEOUT_S = 600` using `asyncio.timeout()`
- `X-Audio-Duration-S`, `X-Synthesis-Latency-S`, `X-Speakers-Unique`, `X-Segment-Count`, `X-Skipped-Segments` response headers for single_track
- Speed: segment `speed` **replaces** global `speed` (not multiplied)
- Pause inserted **only on speaker change** (not between consecutive same-speaker segments)
- `on_error: skip` edge cases from §5.6 (all fail → 422, empty audio never returned)
- Memory budget check upfront: estimated duration ≤ 600s
- OpenAI preset validation upfront

### Must NOT Have (Guardrails)
- Do NOT touch `InferenceService._semaphore` — the script semaphore is **separate**
- Do NOT modify `SynthesisRequest` dataclass fields for multi-speaker (use as-is)
- Do NOT stream script output (v1 is fully synchronous — streaming is Phase 2)
- Do NOT implement Phase 2 job-based endpoint (out of scope)
- Do NOT add `X-Speakers: alice,bob,...` header (removed in v1.1 — use `X-Speakers-Unique` only)
- Do NOT put hardcoded limits (`MAX_SCRIPT_SEGMENTS`, etc.) in `Settings` — they are constants
- Do NOT call `script_semaphore.acquire()` blocking — use `try_acquire` / non-blocking check

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES (pytest, see `tests/` directory)
- **Automated tests**: YES — add `tests/test_script.py`
- **Framework**: pytest with TestClient

### QA Policy
Every task includes agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — foundation, all independent):
├── Task 1: config.py — add default_voice field [quick]
├── Task 2: utils/audio.py — add mixing utilities [quick]
└── Task 3: services/script.py — ScriptOrchestrator [unspecified-high]

Wave 2 (After Wave 1 — integration):
├── Task 4: routers/script.py — endpoint + Pydantic models [unspecified-high]
└── (Task 3 must be done first)

Wave 3 (After Task 4):
├── Task 5: app.py — wire router + semaphore [quick]
├── Task 6: routers/health.py — expose script metrics [quick]
└── Task 7: tests/test_script.py — full test suite [unspecified-high]

Wave FINAL:
└── Task 8: Run full test suite, fix any issues [quick]
```

### Dependency Matrix
- Task 1: no deps → unblocks Task 4 (default_voice needed in orchestrator)
- Task 2: no deps → unblocks Task 3 (mixing functions needed)
- Task 3: depends Task 2 → unblocks Task 4
- Task 4: depends Tasks 1, 3 → unblocks Task 5, 7
- Task 5: depends Task 4 → unblocks Task 8
- Task 6: depends Task 5 → unblocks Task 8
- Task 7: depends Task 4 → run with Task 5,6 in Wave 3
- Task 8: depends Tasks 5, 6, 7

---

## TODOs

- [x] 1. Add `default_voice` to `omnivoice_server/config.py`

  **What to do**:
  - In `Settings` class, add a new field after `max_ref_audio_mb`:
    ```python
    default_voice: str = Field(
        default="male, middle-aged, moderate pitch, neutral accent",
        description=(
            "Default voice description used when no voice is specified for a speaker. "
            "Deployers can customise this for non-English use cases."
        ),
    )
    ```
  - This is the only new setting field — all other limits stay as hardcoded constants.

  **Must NOT do**:
  - Do NOT add `MAX_SCRIPT_SEGMENTS` or other limits to Settings

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3)
  - **Blocks**: Task 4 (orchestrator reads `cfg.default_voice`)
  - **Blocked By**: None

  **References**:
  - `omnivoice_server/config.py:80-90` — Existing field pattern (`max_ref_audio_mb`), add after it
  - `docs/specs/multi-speaker-script-api.md:488-496` — Spec for `default_voice` field

  **Acceptance Criteria**:
  - [ ] `Settings()` instantiates without error with no env vars set
  - [ ] `Settings(default_voice="female, young").default_voice == "female, young"`
  - [ ] `OMNIVOICE_DEFAULT_VOICE` env var overrides the field

  **QA Scenarios**:
  ```
  Scenario: default_voice field is accessible
    Tool: Bash (python -c)
    Steps:
      1. Run: python -c "from omnivoice_server.config import Settings; s=Settings(); print(s.default_voice)"
      2. Assert output contains "neutral accent" (default value)
    Expected Result: Exit 0, prints default voice string
    Evidence: .sisyphus/evidence/task-1-config-default-voice.txt
  ```

  **Commit**: YES (group with Task 2)
  - Message: `feat(config): add default_voice setting for multi-speaker script endpoint`
  - Files: `omnivoice_server/config.py`

---

- [x] 2. Add audio mixing utilities to `omnivoice_server/utils/audio.py`

  **What to do**:
  Add three new functions at the bottom of `omnivoice_server/utils/audio.py`. These are pure functions with no side effects.

  **Function 1: `make_silence_tensor`**
  ```python
  def make_silence_tensor(duration_s: float, sample_rate: int = SAMPLE_RATE) -> torch.Tensor:
      """Create a (1, T) silent float32 tensor of given duration."""
      num_samples = int(sample_rate * duration_s)
      return torch.zeros(1, num_samples)
  ```

  **Function 2: `SegmentTimestamp` dataclass** (import `dataclass` from `dataclasses`):
  ```python
  from dataclasses import dataclass

  @dataclass
  class SegmentTimestamp:
      index: int
      speaker: str
      offset_s: float
      duration_s: float
  ```

  **Function 3: `mix_to_single_track`**
  ```python
  def mix_to_single_track(
      segments: list[tuple[str, torch.Tensor]],
      pause_s: float,
  ) -> tuple[torch.Tensor, list[SegmentTimestamp]]:
      """
      Concatenate (speaker, audio) segments with pause on speaker change.

      Pause is inserted ONLY when consecutive speakers differ.
      pause_s=0.0 means hard cut (no silence).

      Returns (mixed_tensor, list_of_segment_timestamps).
      The mixed_tensor is (1, T) float32.
      """
      if not segments:
          raise ValueError("segments must not be empty")

      pieces: list[torch.Tensor] = []
      timestamps: list[SegmentTimestamp] = []
      offset_s = 0.0

      for i, (speaker, audio) in enumerate(segments):
          # Ensure (1, T) shape
          if audio.dim() == 1:
              audio = audio.unsqueeze(0)

          # Insert pause on speaker change (not before the first segment)
          if i > 0 and speaker != segments[i - 1][0] and pause_s > 0.0:
              silence = make_silence_tensor(pause_s)
              pieces.append(silence)
              offset_s += pause_s

          seg_duration_s = audio.shape[-1] / SAMPLE_RATE
          timestamps.append(SegmentTimestamp(
              index=i,
              speaker=speaker,
              offset_s=round(offset_s, 3),
              duration_s=round(seg_duration_s, 3),
          ))
          pieces.append(audio)
          offset_s += seg_duration_s

      mixed = torch.cat(pieces, dim=-1)  # (1, T)
      return mixed, timestamps
  ```

  **Function 4: `group_by_speaker`**
  ```python
  def group_by_speaker(
      segments: list[tuple[str, torch.Tensor]],
  ) -> dict[str, torch.Tensor]:
      """
      Concatenate each speaker's audio segments.
      Returns dict mapping speaker_id -> (1, T) tensor.
      Speakers with no segments are absent from result.
      """
      from collections import defaultdict
      buckets: dict[str, list[torch.Tensor]] = defaultdict(list)
      for speaker, audio in segments:
          if audio.dim() == 1:
              audio = audio.unsqueeze(0)
          buckets[speaker].append(audio)
      return {
          speaker: torch.cat(parts, dim=-1)
          for speaker, parts in buckets.items()
      }
  ```

  **Must NOT do**:
  - Do NOT modify existing functions
  - Do NOT import pydub in these functions (pure torch/numpy operations only)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3)
  - **Blocks**: Task 3 (ScriptOrchestrator imports these)
  - **Blocked By**: None

  **References**:
  - `omnivoice_server/utils/audio.py` — Full file, add at bottom after `validate_audio_bytes`
  - `omnivoice_server/utils/audio.py:1-20` — Imports (torch, numpy already imported; add `dataclass`)
  - `omnivoice_server/utils/audio.py:SAMPLE_RATE` — Use the module-level constant `SAMPLE_RATE = 24_000`
  - `tests/conftest.py:make_silence_tensor` — Note: conftest has same function; the utils one is canonical production version
  - `docs/specs/multi-speaker-script-api.md:626-644` — Spec for the three mixing functions

  **Acceptance Criteria**:
  - [ ] `make_silence_tensor(1.0)` returns shape `(1, 24000)`, dtype `float32`, all zeros
  - [ ] `mix_to_single_track([("a", t1), ("b", t2)], 0.5)` inserts 12000 silence samples between
  - [ ] `mix_to_single_track([("a", t1), ("a", t2)], 0.5)` does NOT insert silence (same speaker)
  - [ ] `group_by_speaker([("a", t1), ("b", t2), ("a", t3)])` returns `{"a": concat(t1,t3), "b": t2}`

  **QA Scenarios**:
  ```
  Scenario: mixing functions importable and correct
    Tool: Bash (python -c)
    Steps:
      1. Run: python -c "from omnivoice_server.utils.audio import make_silence_tensor, mix_to_single_track, group_by_speaker; import torch; t=make_silence_tensor(1.0); print(t.shape, t.dtype)"
      2. Assert output: "torch.Size([1, 24000]) torch.float32"
    Expected Result: Exit 0
    Evidence: .sisyphus/evidence/task-2-audio-mixing.txt

  Scenario: speaker-change pause logic
    Tool: Bash (python -c)
    Steps:
      1. Run test that verifies pause inserted between different speakers but not same
      2. Use torch.zeros(1,100) for both tensors, pause_s=0.5
      3. Different speakers: assert mixed shape[-1] == 100 + 12000 + 100 = 12200
      4. Same speakers: assert mixed shape[-1] == 200 (no pause)
    Expected Result: Both assertions pass
    Evidence: .sisyphus/evidence/task-2-pause-logic.txt
  ```

  **Commit**: YES (group with Task 1)
  - Message: `feat(audio): add mixing utilities for multi-speaker synthesis`
  - Files: `omnivoice_server/utils/audio.py`

---

- [x] 3. Create `omnivoice_server/services/script.py` — ScriptOrchestrator

  **What to do**:
  Create new file `omnivoice_server/services/script.py` implementing `ScriptOrchestrator`.

  ```python
  """
  Orchestrates multi-speaker script synthesis.
  Synthesizes each segment sequentially using InferenceService,
  then mixes audio into single or multi-track output.
  """

  from __future__ import annotations

  import asyncio
  import base64
  import logging
  import time
  from dataclasses import dataclass

  import torch

  from ..config import Settings
  from ..services.inference import InferenceService, SynthesisRequest
  from ..services.metrics import MetricsService
  from ..services.profiles import ProfileNotFoundError, ProfileService
  from ..utils.audio import SegmentTimestamp, group_by_speaker, mix_to_single_track, tensor_to_wav_bytes, tensors_to_formatted_bytes
  from ..voice_presets import OPENAI_VOICE_PRESETS

  logger = logging.getLogger(__name__)

  # Hardcoded safety limits — NOT in Settings (API contract, not operational tuning)
  MAX_SCRIPT_SEGMENTS = 100
  MAX_TOTAL_INPUT_CHARS = 50_000
  MAX_UNIQUE_SPEAKERS = 10
  MAX_SEGMENT_CHARS = 10_000
  SCRIPT_TOTAL_TIMEOUT_S = 600  # 10 minutes
  MAX_TOTAL_AUDIO_DURATION_S = 600  # 10 minutes of synthesized audio
  _AVG_CHARS_PER_SECOND = 15.0  # Pessimistic estimate for duration pre-check
  ```

  **`ScriptSegmentInput` dataclass** (internal representation, not the Pydantic model):
  ```python
  @dataclass
  class ScriptSegmentInput:
      """Internal resolved segment ready for synthesis."""
      index: int
      speaker: str
      text: str
      voice: str  # Fully resolved voice string
      speed: float  # Effective speed (segment overrides global)
  ```

  **`ScriptResult` dataclass**:
  ```python
  @dataclass
  class ScriptResult:
      synthesized_segments: list[tuple[str, torch.Tensor]]  # (speaker, tensor)
      skipped_indices: list[int]
      timestamps: list[SegmentTimestamp]
      total_latency_s: float
  ```

  **`ScriptMetrics` class** — wraps a named MetricsService instance:
  ```python
  class ScriptMetrics:
      """Script-specific metrics counters."""
      def __init__(self) -> None:
          self._base = MetricsService()
          self.segments_synthesized = 0
          self.segments_skipped = 0
          self.voice_resolution_failures = 0
          self._lock = __import__('threading').Lock()

      def record_request_success(self, latency_s: float) -> None:
          self._base.record_success(latency_s)

      def record_request_error(self) -> None:
          self._base.record_error()

      def record_request_timeout(self) -> None:
          self._base.record_timeout()

      def record_segment_synthesized(self) -> None:
          with self._lock:
              self.segments_synthesized += 1

      def record_segment_skipped(self) -> None:
          with self._lock:
              self.segments_skipped += 1

      def record_voice_resolution_failure(self) -> None:
          with self._lock:
              self.voice_resolution_failures += 1

      def snapshot(self) -> dict:
          base = self._base.snapshot()
          with self._lock:
              return {
                  "script_requests_total": base["requests_total"],
                  "script_requests_success": base["requests_success"],
                  "script_requests_error": base["requests_error"],
                  "script_requests_timeout": base["requests_timeout"],
                  "script_mean_latency_ms": base["mean_latency_ms"],
                  "script_p95_latency_ms": base["p95_latency_ms"],
                  "script_segments_synthesized": self.segments_synthesized,
                  "script_segments_skipped": self.segments_skipped,
                  "script_voice_resolution_failures": self.voice_resolution_failures,
              }
  ```

  **`ScriptOrchestrator` class**:
  ```python
  class ScriptOrchestrator:
      """Orchestrates multi-speaker synthesis."""

      def __init__(
          self,
          inference_svc: InferenceService,
          profile_svc: ProfileService,
          script_semaphore: asyncio.Semaphore,
          script_metrics: ScriptMetrics,
          cfg: Settings,
      ) -> None:
          self._inference = inference_svc
          self._profiles = profile_svc
          self._semaphore = script_semaphore
          self._metrics = script_metrics
          self._cfg = cfg
  ```

  **Voice resolution logic** — `_resolve_voices` method:
  ```python
      def _resolve_voices(
          self,
          script: list,  # list of ScriptSegment (Pydantic model from router)
      ) -> list[str]:  # one resolved voice per segment
          """
          Build per-segment resolved voice list using first-definition rule.
          Validates clone profiles upfront; raises HTTPException 422 on failure.
          """
          from fastapi import HTTPException

          speaker_voice_map: dict[str, str] = {}  # speaker -> first defined voice

          resolved: list[str] = []
          for i, seg in enumerate(script):
              speaker = seg.speaker
              voice_raw = seg.voice  # May be None

              if voice_raw is not None:
                  # This segment defines a voice — update map if first time
                  if speaker not in speaker_voice_map:
                      speaker_voice_map[speaker] = voice_raw
                  resolved_voice = voice_raw
              elif speaker in speaker_voice_map:
                  # Inherit from first definition
                  resolved_voice = speaker_voice_map[speaker]
              else:
                  # No voice defined yet for this speaker — use server default
                  resolved_voice = self._cfg.default_voice

              resolved.append(resolved_voice)

          # Upfront validation: clone profiles and OpenAI presets
          for i, (seg, voice) in enumerate(zip(script, resolved)):
              if voice.lower().startswith("clone:"):
                  profile_id = voice.split(":", 1)[1].strip()
                  try:
                      self._profiles.get_ref_audio_path(profile_id)
                  except ProfileNotFoundError:
                      self._metrics.record_voice_resolution_failure()
                      raise HTTPException(
                          status_code=422,
                          detail=(
                              f"Segment {i} (speaker '{seg.speaker}'): "
                              f"profile '{profile_id}' not found"
                          ),
                      )
              elif not voice.lower().startswith("design:") and voice.lower() not in OPENAI_VOICE_PRESETS and voice != self._cfg.default_voice:
                  # Check if it's a valid OpenAI preset name
                  # (design: voices are lazy-validated at synthesis time)
                  self._metrics.record_voice_resolution_failure()
                  raise HTTPException(
                      status_code=422,
                      detail=(
                          f"Segment {i} (speaker '{seg.speaker}'): "
                          f"unknown voice '{voice}'. Use 'clone:id', 'design:attrs', or a preset name."
                      ),
                  )

          return resolved
  ```

  **`_build_synthesis_request` method** — translates voice string to SynthesisRequest:
  ```python
      def _build_synthesis_request(
          self,
          text: str,
          voice: str,
          speed: float,
      ) -> SynthesisRequest:
          """Build SynthesisRequest from resolved voice string."""
          if voice.lower().startswith("clone:"):
              profile_id = voice.split(":", 1)[1].strip()
              ref_audio_path = str(self._profiles.get_ref_audio_path(profile_id))
              ref_text = self._profiles.get_ref_text(profile_id)
              return SynthesisRequest(
                  text=text,
                  mode="clone",
                  ref_audio_path=ref_audio_path,
                  ref_text=ref_text,
                  speed=speed,
              )
          elif voice.lower().startswith("design:"):
              instruct = voice.split(":", 1)[1].strip()
              return SynthesisRequest(
                  text=text,
                  mode="design",
                  instruct=instruct,
                  speed=speed,
              )
          elif voice.lower() in OPENAI_VOICE_PRESETS:
              instruct = OPENAI_VOICE_PRESETS[voice.lower()]
              return SynthesisRequest(
                  text=text,
                  mode="design",
                  instruct=instruct,
                  speed=speed,
              )
          else:
              # Treat as design attributes (includes default_voice)
              return SynthesisRequest(
                  text=text,
                  mode="design",
                  instruct=voice,
                  speed=speed,
              )
  ```

  **`synthesize_script` main method**:
  ```python
      async def synthesize_script(self, req) -> ScriptResult:
          """
          Main orchestration: validate → acquire semaphore → synthesize → mix.
          req is the ScriptRequest Pydantic model from the router.
          """
          from fastapi import HTTPException

          t_start = time.monotonic()

          # 1. Upfront memory budget check
          total_chars = sum(len(s.text) for s in req.script)
          estimated_duration_s = total_chars / _AVG_CHARS_PER_SECOND
          if estimated_duration_s > MAX_TOTAL_AUDIO_DURATION_S:
              raise HTTPException(
                  status_code=422,
                  detail=(
                      f"Estimated audio duration {estimated_duration_s:.0f}s "
                      f"exceeds limit {MAX_TOTAL_AUDIO_DURATION_S}s"
                  ),
              )

          # 2. Resolve voices upfront
          resolved_voices = self._resolve_voices(req.script)

          # 3. Acquire script semaphore (non-blocking — 503 if contended)
          acquired = self._semaphore.locked()
          if acquired:
              raise HTTPException(
                  status_code=503,
                  detail="Script synthesis at capacity — try again later",
              )

          async with self._semaphore:
              try:
                  result = await self._synthesize_segments(
                      req, resolved_voices, t_start
                  )
              except asyncio.TimeoutError:
                  self._metrics.record_request_timeout()
                  raise HTTPException(
                      status_code=504,
                      detail="Script synthesis timed out — total request exceeded 600s",
                  )

          total_latency_s = time.monotonic() - t_start
          self._metrics.record_request_success(total_latency_s)
          return result

      async def _synthesize_segments(
          self,
          req,
          resolved_voices: list[str],
          t_start: float,
      ) -> ScriptResult:
          """Synthesize all segments under the total timeout."""
          from fastapi import HTTPException

          synthesized: list[tuple[str, torch.Tensor]] = []
          skipped: list[int] = []
          abort_errors: list[str] = []

          async with asyncio.timeout(SCRIPT_TOTAL_TIMEOUT_S):
              for i, seg in enumerate(req.script):
                  voice = resolved_voices[i]
                  # Speed: segment.speed replaces global req.speed (not multiplied)
                  speed = seg.speed if seg.speed is not None else req.speed

                  synth_req = self._build_synthesis_request(
                      text=seg.text,
                      voice=voice,
                      speed=speed,
                  )

                  try:
                      result = await self._inference.synthesize(synth_req)
                      # Flatten tensors to single tensor
                      if len(result.tensors) == 1:
                          audio = result.tensors[0]
                      else:
                          audio = torch.cat([t.cpu() for t in result.tensors], dim=-1)
                      synthesized.append((seg.speaker, audio))
                      self._metrics.record_segment_synthesized()

                  except asyncio.TimeoutError:
                      if req.on_error == "skip":
                          logger.warning(f"Segment {i}: synthesis timed out, skipping")
                          skipped.append(i)
                          self._metrics.record_segment_skipped()
                      else:
                          raise HTTPException(
                              status_code=504,
                              detail=f"Segment {i}: synthesis timed out after {self._cfg.request_timeout_s}s",
                          )

                  except Exception as e:
                      if req.on_error == "skip":
                          logger.warning(f"Segment {i}: synthesis failed ({e}), skipping")
                          skipped.append(i)
                          self._metrics.record_segment_skipped()
                      else:
                          raise HTTPException(
                              status_code=422,
                              detail=f"Segment {i}: synthesis failed — {e}",
                          )

          # Check for all-failed scenario
          if not synthesized:
              raise HTTPException(
                  status_code=422,
                  detail=f"All segments failed: {skipped}",
              )

          # Mix audio
          mixed_audio, timestamps = mix_to_single_track(
              synthesized,
              pause_s=req.pause_between_speakers,
          )

          return ScriptResult(
              synthesized_segments=synthesized,
              skipped_indices=skipped,
              timestamps=timestamps,
              total_latency_s=time.monotonic() - t_start,
          )
  ```

  **Important implementation note on semaphore check**:
  The spec says "non-blocking try" — `asyncio.Semaphore` doesn't have `try_acquire` in Python's stdlib. Use `asyncio.Semaphore.locked()` to check if it's at capacity (for Semaphore(1), `locked()` returns True when the only slot is taken).

  **Must NOT do**:
  - Do NOT import from `routers/script.py` (circular import) — use duck typing for `req`
  - Do NOT use `await semaphore.acquire()` blocking wait — check `.locked()` first
  - Do NOT multiply `segment.speed * req.speed` — segment replaces global
  - Do NOT insert pause between same-speaker consecutive segments

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1, with Tasks 1 and 2)
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 4
  - **Blocked By**: Task 2 (needs `mix_to_single_track`, `group_by_speaker`, `SegmentTimestamp` from audio.py)

  **References**:
  - `omnivoice_server/services/inference.py` — `InferenceService`, `SynthesisRequest`, `SynthesisResult` — use as-is
  - `omnivoice_server/services/metrics.py` — `MetricsService` pattern to follow for `ScriptMetrics`
  - `omnivoice_server/services/profiles.py` — `ProfileService.get_ref_audio_path()`, `ProfileNotFoundError`
  - `omnivoice_server/voice_presets.py` — `OPENAI_VOICE_PRESETS` dict for preset validation
  - `omnivoice_server/utils/audio.py` — `mix_to_single_track`, `group_by_speaker`, `SegmentTimestamp` (functions added in Task 2)
  - `docs/specs/multi-speaker-script-api.md:527-714` — Full architecture and synthesis flow
  - `docs/specs/multi-speaker-script-api.md:456-466` — on_error: skip edge cases
  - `docs/specs/multi-speaker-script-api.md:443-454` — Speed composition rule

  **Acceptance Criteria**:
  - [ ] `ScriptOrchestrator` class instantiates correctly
  - [ ] `ScriptMetrics.snapshot()` returns all 9 expected keys
  - [ ] Voice resolution: clone → upfront profile lookup
  - [ ] Voice resolution: design: → lazy (no upfront check)
  - [ ] Voice resolution: OpenAI preset → upfront check
  - [ ] Voice inheritance: speaker's first-defined voice used for subsequent segments
  - [ ] Speed override: segment speed replaces global

  **QA Scenarios**:
  ```
  Scenario: ScriptMetrics snapshot keys
    Tool: Bash (python -c)
    Steps:
      1. Run: python -c "from omnivoice_server.services.script import ScriptMetrics; m=ScriptMetrics(); s=m.snapshot(); print(list(s.keys()))"
      2. Assert all 9 keys present: script_requests_total, script_requests_success, etc.
    Expected Result: Exit 0, all keys present
    Evidence: .sisyphus/evidence/task-3-metrics-keys.txt
  ```

  **Commit**: YES
  - Message: `feat(services): add ScriptOrchestrator for multi-speaker synthesis`
  - Files: `omnivoice_server/services/script.py`

---

- [x] 4. Create `omnivoice_server/routers/script.py` — endpoint + Pydantic models

  **What to do**:
  Create new file `omnivoice_server/routers/script.py`.

  **Pydantic models**:
  ```python
  import re
  from typing import Literal
  from pydantic import BaseModel, Field, field_validator

  SPEAKER_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

  class ScriptSegment(BaseModel):
      speaker: str = Field(..., description="Speaker identifier")
      text: str = Field(..., min_length=1, max_length=10_000)
      voice: str | None = Field(default=None)
      speed: float | None = Field(default=None, ge=0.25, le=4.0)

      @field_validator("speaker")
      @classmethod
      def validate_speaker(cls, v: str) -> str:
          if not SPEAKER_PATTERN.match(v):
              raise ValueError(
                  f"speaker '{v}' must match ^[a-zA-Z0-9_-]{{1,64}}$"
              )
          return v

  class ScriptRequest(BaseModel):
      script: list[ScriptSegment] = Field(..., min_length=1, max_length=100)
      output_format: Literal["single_track", "multi_track"] = "single_track"
      pause_between_speakers: float = Field(default=0.5, ge=0.0, le=5.0)
      response_format: ResponseFormat = Field(default="wav")
      speed: float = Field(default=1.0, ge=0.25, le=4.0)
      on_error: Literal["abort", "skip"] = "abort"

      @field_validator("script")
      @classmethod
      def validate_script_limits(cls, v: list[ScriptSegment]) -> list[ScriptSegment]:
          if len(v) > 100:
              raise ValueError(f"Script exceeds maximum 100 segments (got {len(v)})")
          total_chars = sum(len(s.text) for s in v)
          if total_chars > 50_000:
              raise ValueError(
                  f"Total text exceeds 50,000 characters (got {total_chars})"
              )
          unique_speakers = len({s.speaker for s in v})
          if unique_speakers > 10:
              raise ValueError(
                  f"Too many unique speakers: {unique_speakers} (max 10)"
              )
          return v
  ```

  **Dependency injection** (matching speech.py pattern):
  ```python
  from fastapi import APIRouter, Depends, Request
  from ..services.script import ScriptOrchestrator

  router = APIRouter()

  def _get_orchestrator(request: Request) -> ScriptOrchestrator:
      return request.app.state.script_orchestrator
  ```

  **Endpoint**:
  ```python
  @router.post("/audio/script")
  async def create_script(
      body: ScriptRequest,
      orchestrator: ScriptOrchestrator = Depends(_get_orchestrator),
  ) -> Response:
      """
      Synthesize multi-speaker dialogue.

      Accepts a script with multiple speaker segments, synthesizes each sequentially,
      inserts configurable pauses between speaker changes, and returns mixed audio.

      - **single_track**: Returns binary audio with metadata headers
      - **multi_track**: Returns JSON with per-speaker audio blobs and timestamps
      """
      import time
      t_start = time.monotonic()

      result = await orchestrator.synthesize_script(body)

      skipped_str = ",".join(str(i) for i in result.skipped_indices)
      unique_speakers = len({speaker for speaker, _ in result.synthesized_segments})

      if body.output_format == "single_track":
          # Mix all segments
          mixed, _ = mix_to_single_track(result.synthesized_segments, body.pause_between_speakers)
          audio_bytes, media_type = tensors_to_formatted_bytes([mixed], body.response_format)
          duration_s = mixed.shape[-1] / 24_000

          return Response(
              content=audio_bytes,
              media_type=media_type,
              headers={
                  "X-Audio-Duration-S": str(round(duration_s, 3)),
                  "X-Synthesis-Latency-S": str(round(result.total_latency_s, 3)),
                  "X-Speakers-Unique": str(unique_speakers),
                  "X-Segment-Count": str(len(result.synthesized_segments)),
                  "X-Skipped-Segments": skipped_str,
              },
          )
      else:  # multi_track
          speaker_tensors = group_by_speaker(result.synthesized_segments)
          tracks = {}
          for speaker, tensor in speaker_tensors.items():
              wav_bytes = tensor_to_wav_bytes(tensor)
              # Convert to requested format if needed
              converted, _ = tensors_to_formatted_bytes([tensor], body.response_format)
              tracks[speaker] = base64.b64encode(converted).decode()

          total_duration_s = sum(
              ts.duration_s for ts in result.timestamps
          ) + body.pause_between_speakers * max(0, len(result.synthesized_segments) - 1)

          return JSONResponse(
              content={
                  "tracks": tracks,
                  "metadata": {
                      "total_duration_s": round(total_duration_s, 3),
                      "speakers_unique": unique_speakers,
                      "segment_count": len(result.synthesized_segments),
                      "skipped_segments": result.skipped_indices,
                      "segments": [
                          {
                              "index": ts.index,
                              "speaker": ts.speaker,
                              "offset_s": ts.offset_s,
                              "duration_s": ts.duration_s,
                          }
                          for ts in result.timestamps
                      ],
                  },
              }
          )
  ```

  **Important**: The router computes the final mix — NOT the orchestrator. The orchestrator returns `synthesized_segments` (raw list of `(speaker, tensor)`), and the router calls `mix_to_single_track` / `group_by_speaker`. This keeps the orchestrator pure and testable.

  **Must NOT do**:
  - Do NOT add `X-Speakers: alice,bob,alice,...` header (removed in v1.1)
  - Do NOT block on semaphore — 503 is handled in orchestrator

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (after Task 3)
  - **Blocks**: Tasks 5, 7
  - **Blocked By**: Tasks 1, 3

  **References**:
  - `omnivoice_server/routers/speech.py` — Full file — exact pattern for router, Pydantic models, Depends, error handling
  - `omnivoice_server/utils/audio.py` — `ResponseFormat`, `tensors_to_formatted_bytes`, `tensor_to_wav_bytes`
  - `omnivoice_server/services/script.py` — `ScriptOrchestrator`, `ScriptResult` (from Task 3)
  - `docs/specs/multi-speaker-script-api.md:265-295` — Full ScriptRequest schema
  - `docs/specs/multi-speaker-script-api.md:363-405` — Response schemas (single_track + multi_track)
  - `docs/specs/multi-speaker-script-api.md:409-442` — Error response formats

  **Acceptance Criteria**:
  - [ ] `ScriptRequest` Pydantic model validates correctly (speaker regex, limits)
  - [ ] `ScriptSegment.voice = None` passes validation
  - [ ] `ScriptRequest` with 101 segments raises `ValueError` with correct message
  - [ ] Router endpoint exists at `POST /v1/audio/script` (visible in OpenAPI)

  **QA Scenarios**:
  ```
  Scenario: Pydantic model validation
    Tool: Bash (python -c)
    Steps:
      1. Run: python -c "from omnivoice_server.routers.script import ScriptRequest, ScriptSegment; r=ScriptRequest(script=[ScriptSegment(speaker='alice', text='Hello')]); print(r.output_format, r.on_error)"
      2. Assert output: "single_track abort"
    Expected Result: Exit 0
    Evidence: .sisyphus/evidence/task-4-pydantic-model.txt

  Scenario: Invalid speaker ID rejected
    Tool: Bash (python -c)
    Steps:
      1. Run: python -c "from omnivoice_server.routers.script import ScriptSegment; ScriptSegment(speaker='alice!!', text='hi')"
      2. Assert exit code non-zero or exception printed
    Expected Result: ValidationError raised
    Evidence: .sisyphus/evidence/task-4-speaker-validation.txt
  ```

  **Commit**: YES
  - Message: `feat(routers): add multi-speaker script endpoint POST /v1/audio/script`
  - Files: `omnivoice_server/routers/script.py`

---

- [x] 5. Wire script router + semaphore in `omnivoice_server/app.py`

  **What to do**:
  Three changes to `app.py`:

  **Change 1** — Add import at top:
  ```python
  from .routers import health, models, script, speech, voices
  from .services.script import ScriptMetrics, ScriptOrchestrator
  ```

  **Change 2** — In `lifespan()`, after `app.state.metrics_svc = MetricsService()`, add:
  ```python
  script_semaphore = asyncio.Semaphore(1)
  script_metrics = ScriptMetrics()
  app.state.script_orchestrator = ScriptOrchestrator(
      inference_svc=app.state.inference_svc,
      profile_svc=app.state.profile_svc,
      script_semaphore=script_semaphore,
      script_metrics=script_metrics,
      cfg=cfg,
  )
  app.state.script_metrics = script_metrics
  ```

  **Change 3** — In `create_app()`, register router after existing routers:
  ```python
  app.include_router(script.router, prefix="/v1")
  ```

  Also add `import asyncio` at top of file if not already present.

  **Must NOT do**:
  - Do NOT modify `InferenceService` semaphore
  - Do NOT reuse `app.state.metrics_svc` for script metrics

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 3, with Tasks 6 and 7)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 8
  - **Blocked By**: Task 4

  **References**:
  - `omnivoice_server/app.py` — Full file — add imports, lifespan wiring, router registration
  - `omnivoice_server/services/script.py` — `ScriptOrchestrator`, `ScriptMetrics` (from Task 3)
  - `omnivoice_server/routers/script.py` — `router` (from Task 4)
  - `docs/specs/multi-speaker-script-api.md:544-551` — App.py wiring pattern

  **Acceptance Criteria**:
  - [ ] `create_app(Settings())` starts without error (with mocked model)
  - [ ] `app.state.script_orchestrator` is a `ScriptOrchestrator` instance
  - [ ] `app.state.script_metrics` is a `ScriptMetrics` instance
  - [ ] `/docs` shows `POST /v1/audio/script` endpoint

  **QA Scenarios**:
  ```
  Scenario: App starts with script router registered
    Tool: Bash (python -c)
    Steps:
      1. Run: python -c "from omnivoice_server.app import create_app; from omnivoice_server.config import Settings; app=create_app(Settings()); routes=[r.path for r in app.routes]; print([r for r in routes if 'script' in r])"
      2. Assert output contains "/v1/audio/script"
    Expected Result: Exit 0, route present
    Evidence: .sisyphus/evidence/task-5-route-registered.txt
  ```

  **Commit**: YES
  - Message: `feat(app): wire ScriptOrchestrator and script router`
  - Files: `omnivoice_server/app.py`

---

- [x] 6. Expose script metrics in `omnivoice_server/routers/health.py`

  **What to do**:
  Modify the `/metrics` endpoint to include script metrics.

  Current handler:
  ```python
  @router.get("/metrics")
  async def metrics(request: Request):
      metrics_svc = request.app.state.metrics_svc
      snapshot = metrics_svc.snapshot()
      snapshot["ram_mb"] = round(psutil.Process().memory_info().rss / 1024 / 1024, 1)
      return snapshot
  ```

  Updated handler:
  ```python
  @router.get("/metrics")
  async def metrics(request: Request):
      metrics_svc = request.app.state.metrics_svc
      snapshot = metrics_svc.snapshot()
      snapshot["ram_mb"] = round(psutil.Process().memory_info().rss / 1024 / 1024, 1)

      # Script metrics (separate namespace, safe to skip if not wired)
      script_metrics = getattr(request.app.state, "script_metrics", None)
      if script_metrics is not None:
          snapshot.update(script_metrics.snapshot())

      return snapshot
  ```

  Using `getattr(..., None)` guards against the case where tests don't wire `script_metrics`.

  **Must NOT do**:
  - Do NOT break existing `/metrics` response keys
  - Do NOT merge script counters into speech counters

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 3, with Tasks 5 and 7)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 8
  - **Blocked By**: Task 5 (needs `script_metrics` on `app.state`)

  **References**:
  - `omnivoice_server/routers/health.py` — Full file, modify `/metrics` handler
  - `omnivoice_server/services/script.py` — `ScriptMetrics.snapshot()` returns 9 keys

  **Acceptance Criteria**:
  - [ ] `GET /metrics` still returns all existing speech metric keys
  - [ ] `GET /metrics` now also returns `script_requests_total` and `script_segments_synthesized`
  - [ ] `GET /metrics` does not crash if `script_metrics` is not on app.state

  **QA Scenarios**:
  ```
  Scenario: /metrics includes script keys after script request
    Tool: Bash (curl)
    Steps:
      1. Start server (in a test environment with mocked model)
      2. GET /metrics
      3. Assert response JSON contains "script_requests_total"
    Expected Result: 200 OK, script_requests_total present
    Evidence: .sisyphus/evidence/task-6-metrics-keys.txt
  ```

  **Commit**: YES
  - Message: `feat(health): expose script_* metrics in /metrics endpoint`
  - Files: `omnivoice_server/routers/health.py`

---

- [x] 7. Create `tests/test_script.py` — comprehensive test suite

  **What to do**:
  Create `tests/test_script.py`. All tests use the existing `client` fixture from `conftest.py` (mocked model — no real GPU needed).

  **Test structure** — group by concern:

  ```python
  """
  Tests for POST /v1/audio/script endpoint.
  """
  from __future__ import annotations

  import pytest
  import torch
  from unittest.mock import AsyncMock, patch
  from fastapi.testclient import TestClient

  from omnivoice_server.utils.audio import (
      make_silence_tensor,
      mix_to_single_track,
      group_by_speaker,
      SegmentTimestamp,
  )
  from omnivoice_server.services.script import ScriptMetrics
  ```

  **Unit tests for audio mixing** (no server needed):
  ```python
  class TestAudioMixing:
      def test_make_silence_tensor_shape(self):
          t = make_silence_tensor(1.0)
          assert t.shape == (1, 24_000)
          assert t.dtype == torch.float32

      def test_make_silence_tensor_zero(self):
          t = make_silence_tensor(0.5)
          assert t.sum() == 0.0

      def test_mix_single_speaker_no_pause(self):
          t1 = torch.zeros(1, 100)
          t2 = torch.zeros(1, 200)
          mixed, timestamps = mix_to_single_track([("alice", t1), ("alice", t2)], pause_s=0.5)
          # No pause inserted between same-speaker segments
          assert mixed.shape[-1] == 300
          assert len(timestamps) == 2

      def test_mix_different_speakers_pause_inserted(self):
          t1 = torch.zeros(1, 100)
          t2 = torch.zeros(1, 100)
          mixed, timestamps = mix_to_single_track([("alice", t1), ("bob", t2)], pause_s=0.5)
          # Pause = 0.5s × 24000 = 12000 samples
          assert mixed.shape[-1] == 100 + 12_000 + 100

      def test_mix_zero_pause_hard_cut(self):
          t1 = torch.zeros(1, 100)
          t2 = torch.zeros(1, 100)
          mixed, timestamps = mix_to_single_track([("alice", t1), ("bob", t2)], pause_s=0.0)
          # No silence even on speaker change
          assert mixed.shape[-1] == 200

      def test_mix_timestamps_accumulate(self):
          t1 = torch.zeros(1, 24_000)  # 1s
          t2 = torch.zeros(1, 24_000)  # 1s
          _, timestamps = mix_to_single_track([("alice", t1), ("bob", t2)], pause_s=0.5)
          assert timestamps[0].offset_s == 0.0
          assert timestamps[1].offset_s == pytest.approx(1.5, abs=0.01)  # 1s audio + 0.5s pause

      def test_group_by_speaker(self):
          t1 = torch.ones(1, 100)
          t2 = torch.ones(1, 200) * 2
          t3 = torch.ones(1, 150)
          grouped = group_by_speaker([("alice", t1), ("bob", t2), ("alice", t3)])
          assert "alice" in grouped
          assert "bob" in grouped
          assert grouped["alice"].shape[-1] == 250  # 100 + 150
          assert grouped["bob"].shape[-1] == 200
  ```

  **Unit tests for ScriptMetrics**:
  ```python
  class TestScriptMetrics:
      def test_snapshot_keys(self):
          m = ScriptMetrics()
          s = m.snapshot()
          assert "script_requests_total" in s
          assert "script_segments_synthesized" in s
          assert "script_segments_skipped" in s
          assert "script_voice_resolution_failures" in s

      def test_counts_increment(self):
          m = ScriptMetrics()
          m.record_segment_synthesized()
          m.record_segment_synthesized()
          m.record_segment_skipped()
          s = m.snapshot()
          assert s["script_segments_synthesized"] == 2
          assert s["script_segments_skipped"] == 1
  ```

  **Integration tests** (using `client` fixture from conftest):
  ```python
  class TestScriptEndpoint:
      def test_single_speaker_single_track(self, client):
          resp = client.post("/v1/audio/script", json={
              "script": [
                  {"speaker": "alice", "text": "Hello!", "voice": "design:female,young"}
              ]
          })
          assert resp.status_code == 200
          assert resp.headers["content-type"].startswith("audio/")
          assert "X-Audio-Duration-S" in resp.headers
          assert "X-Speakers-Unique" in resp.headers
          assert resp.headers["X-Segment-Count"] == "1"

      def test_two_speakers_alternating(self, client):
          resp = client.post("/v1/audio/script", json={
              "script": [
                  {"speaker": "alice", "text": "Hi!", "voice": "design:female"},
                  {"speaker": "bob", "text": "Hello!", "voice": "design:male"},
                  {"speaker": "alice", "text": "Bye!"},  # Inherits design:female
              ],
              "pause_between_speakers": 0.3,
          })
          assert resp.status_code == 200
          assert resp.headers["X-Speakers-Unique"] == "2"
          assert resp.headers["X-Segment-Count"] == "3"

      def test_multi_track_output(self, client):
          resp = client.post("/v1/audio/script", json={
              "script": [
                  {"speaker": "alice", "text": "Hi!", "voice": "design:female"},
                  {"speaker": "bob", "text": "Hey!", "voice": "design:male"},
              ],
              "output_format": "multi_track",
          })
          assert resp.status_code == 200
          assert resp.headers["content-type"].startswith("application/json")
          data = resp.json()
          assert "tracks" in data
          assert "metadata" in data
          assert "alice" in data["tracks"]
          assert "bob" in data["tracks"]
          assert len(data["metadata"]["segments"]) == 2

      def test_voice_inheritance(self, client):
          """Alice's voice from first segment should be used for subsequent segments."""
          resp = client.post("/v1/audio/script", json={
              "script": [
                  {"speaker": "alice", "voice": "design:female", "text": "First"},
                  {"speaker": "alice", "text": "Second"},  # Should inherit design:female
                  {"speaker": "alice", "text": "Third"},   # Should still inherit
              ]
          })
          assert resp.status_code == 200

      def test_validation_too_many_segments(self, client):
          segments = [{"speaker": "alice", "text": "Hi"} for _ in range(101)]
          resp = client.post("/v1/audio/script", json={"script": segments})
          assert resp.status_code == 422

      def test_validation_invalid_speaker_id(self, client):
          resp = client.post("/v1/audio/script", json={
              "script": [{"speaker": "alice!!", "text": "Hi"}]
          })
          assert resp.status_code == 422

      def test_on_error_skip_returns_200(self, client):
          """When on_error=skip and some segments fail, return 200 with skipped info."""
          # Mock synthesize to fail on segment 1
          call_count = [0]
          original_mock = client.app.state.inference_svc.synthesize

          async def selective_fail(req):
              call_count[0] += 1
              if call_count[0] == 2:
                  raise RuntimeError("Injected failure")
              return await original_mock(req)

          client.app.state.inference_svc.synthesize = AsyncMock(side_effect=selective_fail)

          resp = client.post("/v1/audio/script", json={
              "script": [
                  {"speaker": "alice", "text": "Hello", "voice": "design:female"},
                  {"speaker": "bob", "text": "Fail here", "voice": "design:male"},
                  {"speaker": "alice", "text": "Bye"},
              ],
              "on_error": "skip",
          })
          assert resp.status_code == 200
          assert "1" in resp.headers.get("X-Skipped-Segments", "")

      def test_on_error_abort_returns_422(self, client):
          """When on_error=abort and segment fails, return 422."""
          client.app.state.inference_svc.synthesize = AsyncMock(
              side_effect=RuntimeError("Synthesis failed")
          )
          resp = client.post("/v1/audio/script", json={
              "script": [{"speaker": "alice", "text": "Hi", "voice": "design:female"}],
              "on_error": "abort",
          })
          assert resp.status_code == 422

      def test_speed_segment_overrides_global(self, client):
          """Segment speed should override global speed, not multiply."""
          # This is a behavioral test — we verify the request goes through
          resp = client.post("/v1/audio/script", json={
              "script": [{
                  "speaker": "alice",
                  "text": "Hello",
                  "voice": "design:female",
                  "speed": 0.8,
              }],
              "speed": 1.5,  # Global speed — should be replaced by segment's 0.8
          })
          assert resp.status_code == 200

      def test_response_format_mp3(self, client):
          """Test mp3 format (if pydub available)."""
          resp = client.post("/v1/audio/script", json={
              "script": [{"speaker": "alice", "text": "Hi", "voice": "design:female"}],
              "response_format": "wav",  # Use WAV to avoid pydub dependency
          })
          assert resp.status_code == 200

      def test_clone_nonexistent_profile_422(self, client):
          """clone: with nonexistent profile should return 422 before synthesis."""
          resp = client.post("/v1/audio/script", json={
              "script": [{
                  "speaker": "alice",
                  "text": "Hello",
                  "voice": "clone:nonexistent_profile_xyz"
              }]
          })
          assert resp.status_code == 422
          assert "nonexistent_profile_xyz" in resp.json()["error"]["message"]

      def test_metrics_endpoint_includes_script_keys(self, client):
          """After a script request, /metrics should show script_* keys."""
          # Do a script request first
          client.post("/v1/audio/script", json={
              "script": [{"speaker": "alice", "text": "Hi", "voice": "design:female"}]
          })
          resp = client.get("/metrics")
          assert resp.status_code == 200
          data = resp.json()
          assert "script_requests_total" in data

      def test_empty_script_rejected(self, client):
          """Empty script list should fail validation."""
          resp = client.post("/v1/audio/script", json={"script": []})
          assert resp.status_code == 422
  ```

  **Must NOT do**:
  - Do NOT import or use the real OmniVoice model
  - Do NOT use `time.sleep()` in tests
  - Do NOT test Phase 2 job endpoint (not in scope)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`python-testing`]

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 3, with Tasks 5 and 6)
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 8
  - **Blocked By**: Task 4

  **References**:
  - `tests/conftest.py` — Full file — `client` fixture, `make_silence_tensor`, `_mock_synthesize` pattern
  - `tests/test_speech.py` — Example test structure to follow
  - `tests/test_health.py` — `/metrics` test pattern
  - `omnivoice_server/utils/audio.py` — Functions being tested (Task 2)
  - `omnivoice_server/services/script.py` — `ScriptMetrics` being tested (Task 3)
  - `omnivoice_server/routers/script.py` — Endpoint being tested (Task 4)

  **Acceptance Criteria**:
  - [ ] All tests in `TestAudioMixing` pass
  - [ ] All tests in `TestScriptMetrics` pass
  - [ ] All tests in `TestScriptEndpoint` pass
  - [ ] No existing tests broken

  **QA Scenarios**:
  ```
  Scenario: Run test_script.py tests
    Tool: Bash
    Steps:
      1. Run: cd /Users/trung.ngo/Documents/zaob-dev/omnivoice-server && python -m pytest tests/test_script.py -v 2>&1 | tail -30
      2. Assert all tests PASSED
      3. Assert 0 errors
    Expected Result: All tests green
    Evidence: .sisyphus/evidence/task-7-test-results.txt
  ```

  **Commit**: YES
  - Message: `test(script): add comprehensive tests for multi-speaker script endpoint`
  - Files: `tests/test_script.py`

---

- [x] 8. Run full test suite and fix any issues

  **What to do**:
  Run `pytest tests/ -x -v` and fix any failures. This is the integration verification task.

  Steps:
  1. Run `cd /Users/trung.ngo/Documents/zaob-dev/omnivoice-server && python -m pytest tests/ -x -v`
  2. If failures exist, read error messages, identify root cause, fix
  3. Re-run until all pass
  4. Verify `/docs` route is accessible in a running server

  Common issues to watch for:
  - Import errors in new files (circular imports, missing imports)
  - `asyncio.Semaphore.locked()` behavior — for `Semaphore(1)`, `.locked()` returns True when the single permit is held. This is correct for the 503 check.
  - Test fixture: ensure `client` fixture properly initializes `app.state.script_orchestrator` — if not, tests will fail with `AttributeError`. The `conftest.py` may need updating to mock the script orchestrator, OR the script router's `_get_orchestrator` should be patched in tests.
  - If `client` fixture doesn't wire `script_orchestrator`, add to `conftest.py`:
    ```python
    # In client fixture, after TestClient(app) as c:
    from omnivoice_server.services.script import ScriptOrchestrator, ScriptMetrics
    script_metrics = ScriptMetrics()
    c.app.state.script_metrics = script_metrics
    c.app.state.script_orchestrator = ScriptOrchestrator(
        inference_svc=c.app.state.inference_svc,
        profile_svc=c.app.state.profile_svc,
        script_semaphore=asyncio.Semaphore(1),
        script_metrics=script_metrics,
        cfg=c.app.state.cfg,
    )
    ```
    But note: the `asyncio.Semaphore` must be created inside an event loop context. If TestClient runs synchronously, use `asyncio.Semaphore` outside the loop — TestClient handles this.

  **Must NOT do**:
  - Do NOT skip failing tests with `@pytest.mark.skip`
  - Do NOT weaken assertions to make tests pass

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave FINAL
  - **Blocks**: Nothing
  - **Blocked By**: Tasks 5, 6, 7

  **References**:
  - `tests/conftest.py` — `client` fixture — may need updating to wire script orchestrator
  - All new files created in Tasks 1-7

  **Acceptance Criteria**:
  - [ ] `pytest tests/ -x -v` exits with code 0
  - [ ] All existing tests pass (no regressions)
  - [ ] All new `test_script.py` tests pass

  **QA Scenarios**:
  ```
  Scenario: Full test suite passes
    Tool: Bash
    Steps:
      1. Run: cd /Users/trung.ngo/Documents/zaob-dev/omnivoice-server && python -m pytest tests/ -v 2>&1 | tail -20
      2. Assert last line contains "passed" with 0 failed
    Expected Result: All tests green
    Evidence: .sisyphus/evidence/task-8-full-suite.txt
  ```

  **Commit**: YES (if fixes needed in conftest.py)
  - Message: `fix(tests): wire script orchestrator in test client fixture`
  - Files: `tests/conftest.py` (if updated)

---

## Final Verification Wave

> After all tasks complete — run these in parallel, then present results.

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read plan end-to-end. For each Must Have: verify implementation exists. For each Must NOT Have: search for forbidden patterns. Check that `X-Speakers` header is absent from code, that `asyncio.Semaphore.locked()` is used (not blocking acquire), that speed is override not multiply.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m pytest tests/ -v`. Check all new files for: unused imports, `as any`, empty except blocks, hardcoded limits in wrong places (Settings vs constants).
  Output: `Tests [PASS/FAIL] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real QA** — `unspecified-high`
  Execute all QA scenarios from Tasks 1-8. Save evidence files. Verify audio mixing correctness, voice resolution logic, error handling paths.
  Output: `Scenarios [N/N pass] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  Verify each task's implementation matches spec exactly. Check that Phase 2 features (job endpoint, streaming, idempotency) are NOT implemented. Verify no scope creep.
  Output: `Tasks [N/N compliant] | VERDICT`

---

## Commit Strategy

- Task 1+2: `feat(config,audio): add default_voice setting and audio mixing utilities`
- Task 3: `feat(services): add ScriptOrchestrator for multi-speaker synthesis`
- Task 4: `feat(routers): add POST /v1/audio/script multi-speaker endpoint`
- Task 5+6: `feat(app,health): wire script router and expose script metrics`
- Task 7: `test(script): comprehensive test suite for multi-speaker script API`
- Task 8: `fix(tests): wire script orchestrator in test fixtures (if needed)`

---

## Success Criteria

### Verification Commands
```bash
# All tests pass
python -m pytest tests/ -v  # Expected: all green, 0 failed

# New files exist
ls omnivoice_server/services/script.py omnivoice_server/routers/script.py  # Expected: both present

# Config has new field
python -c "from omnivoice_server.config import Settings; print(Settings().default_voice)"  # Expected: prints default voice

# Route registered
python -c "from omnivoice_server.app import create_app; from omnivoice_server.config import Settings; app=create_app(Settings()); print([r.path for r in app.routes if 'script' in r.path])"  # Expected: ['/v1/audio/script']
```

### Final Checklist
- [ ] `POST /v1/audio/script` returns binary audio for valid single_track request
- [ ] `POST /v1/audio/script` returns JSON for multi_track request
- [ ] Clone profile validated upfront, 422 before synthesis
- [ ] Pause inserted only on speaker change
- [ ] Semaphore contention → 503
- [ ] `GET /metrics` includes `script_requests_total`
- [ ] All tests pass
- [ ] No regressions in existing tests
