# Streaming TTFA Optimization Plan

## Scope

Target use case: time to first audio for streaming synthesis with a stored voice profile.

Baseline request:

```bash
curl -N -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "This is the first sentence. And this is the second sentence streaming in.",
    "voice": "clone:sky",
    "stream": true
  }' \
  --output streaming_test.wav
```

Primary metric: TTFA for the first emitted PCM bytes.

Secondary metrics:

- First synthesis call latency
- First PCM encode latency
- Total streaming request latency
- Number of synthesis calls triggered by server chunking
- Bytes emitted before stream completion

## Findings

### 1. Per-request memory cleanup is on the critical path

- `gc.collect()` and `torch.cuda.empty_cache()` run in the synthesis finally block.
- On CUDA this can force allocator churn and synchronization before audio is returned.
- This is likely harmful both for TTFA and steady-state chunk-to-chunk latency.

### 2. The streaming path currently waits for oversized text chunks

- The server uses sentence splitting with `max_chars=400`.
- Short neighboring sentences are merged, so the first emitted audio may wait for too much text.
- Current tests explicitly encode this behavior, which biases the server toward fewer synthesis calls rather than faster first audio.

### 3. Stored voice profiles do not cache reusable clone prompt state

- Saved profiles only persist raw WAV plus metadata.
- Every `clone:<profile>` request redoes reference-audio load, silence trimming, and audio-tokenizer encoding upstream.
- For the target use case, this is one of the most obvious avoidable TTFA costs.

### 4. One-shot clone requests add unnecessary disk I/O

- Uploaded reference audio is written to a temp file and then reopened by upstream.
- Passing in-memory audio or a reusable prompt object would remove that round-trip.

### 5. Streaming cannot disable expensive upstream post-processing

- Upstream defaults to `postprocess_output=True`.
- That path removes silence and fades/pads on CPU before bytes are emitted.
- A streaming-first mode should be able to trade some cleanup for lower TTFA.
- Current assessment after deeper timing review: this is probably a small win only.
- Warm measurements showed `first_decode_postprocess_ms` around `16.5 ms` and
  `first_postprocess_ms` around `8.4 ms` on the target request.
- Upstream `postprocess_output=False` only skips silence removal; it still keeps
  volume adjustment and fade/pad.
- That means the likely upside is single-digit milliseconds to roughly `~10 ms`,
  while the risk is worse audible onset due to leading silence surviving in chunk 0.
- Decision for now: do not implement the chunk-0 streaming-fast path before
  production testing.

### 6. The server was missing TTFA-specific observability

- Existing metrics tracked only whole-request latency.
- Streaming requests were effectively counted per chunk instead of per request.
- There was no direct visibility into first-chunk synthesis time, encode time, or stream TTFA.

### 7. Flex Attention is not currently a low-risk inference win on this stack

- OmniVoice advertises support for both Flex Attention and FlashAttention 2.
- The training builder explicitly uses `attn_implementation="flex_attention"`.
- The server inference path currently uses the default backend.
- A direct CUDA benchmark on this machine showed the default backend working as expected,
  with a cached-prompt first-sentence generate mean of about `124.7 ms`.
- The same benchmark with `attn_implementation="flex_attention"` loaded successfully,
  but warmup failed with an Inductor/Triton resource error:
  `No valid triton configs ... out of resource`.
- Current assessment: Flex Attention is benchmark-worthy in other environments, but
  it is not a safe default inference optimization on this machine today.

## Plan

### Phase 1. Observability and measurement

Status: done.

Implementation:

- Add streaming request correlation via `X-Request-Id`.
- Record one streaming observation per request, not per chunk.
- Expose rolling TTFA and first-stage latency metrics at `/metrics`.
- Log a per-stream summary with request ID, mode, profile ID, TTFA, and chunk counts.

Deliverables:

- `/metrics` includes streaming TTFA and latest stream snapshot.
- Curl measurements can be correlated to server logs with the request ID.

### Phase 2. Fix server-side chunking for TTFA

Status: done.

Implementation:

- Stop merging the first streamed chunk so aggressively.
- Prefer emitting the first natural sentence as soon as possible.
- Keep larger chunk merging only for later chunks if needed for throughput.

Validation:

- Compare `planned_synthesis_calls`, TTFA, and total request time before/after.
- Re-run the `clone:sky` curl benchmark with short multi-sentence inputs.

### Phase 3. Cache stored clone prompts

Status: done.

Implementation:

- Precompute and cache reusable voice-clone prompt state for saved profiles.
- Avoid repeated silence trimming and audio-tokenizer encode for `clone:<profile>`.
- Invalidate cache when profiles are created, updated, or deleted.

Validation:

- Measure TTFA reduction for warm `clone:sky` requests.
- Distinguish cold profile-cache misses from warm hits in logs or metrics.

### Phase 4. Remove hot-path cleanup and make it conditional

Status: done.

Implementation:

- Remove unconditional `gc.collect()` and `torch.cuda.empty_cache()` after every synthesis.
- If memory mitigation is still needed, move it behind a debug/maintenance knob or periodic policy.

Validation:

- Compare TTFA and steady-state chunk latency under repeated streaming load.
- Watch RAM/VRAM drift with `/metrics` and benchmark harnesses.

### Phase 5. Add a streaming-fast generation mode

Status: deferred pending production feedback.

Implementation:

- Expose or default streaming requests to faster upstream settings where safe:
  - `postprocess_output=False` for chunk 0 or for all stream chunks
  - optional prompt preprocessing knobs
- Keep the default non-streaming path quality-oriented.

Validation:

- Measure TTFA delta and listen for artifacts on early chunks.
- Decide whether to keep this as default or config-gated behavior.

Current conclusion:

- The likely gain appears too small relative to the audible-risk tradeoff.
- Leave this off the critical path unless production measurements show
  `first_decode_postprocess_ms` becoming a much larger fraction of TTFA.

### Phase 6. CUDA attention and kernel benchmarking

Status: partially investigated.

Implementation:

- Benchmark upstream `attn_implementation="flash_attention_2"` and `"flex_attention"` on CUDA.
- Keep the server-side interface ready to select the best supported attention path.
- Only evaluate `torch.compile` or CUDA graphs after shape bucketing and warmup are defined.

Why this is later:

- Compile and graph capture can easily worsen cold-start TTFA if the shapes stay dynamic.
- The bigger wins are currently in Python-side orchestration and clone-prompt reuse.

Validation:

- Run representative clone-stream TTFA benchmarks on CUDA with each attention mode.
- Track first-request and warm-request behavior separately.

Current results:

- `flash_attn` is not installed in the current `uv` env, so FlashAttention 2 was not
  benchmarked locally.
- `flex_attention` is available via `torch 2.8.0+cu128` and was benchmarked directly.
- Default backend benchmark for the first streamed sentence with cached prompt:
  - runs: `133.2 ms`, `120.0 ms`, `120.7 ms`
  - mean: `124.7 ms`
- `flex_attention` benchmark outcome on this machine:
  - model load: success
  - prompt creation: success
  - warmup generate: failed
  - error: `InductorError` / Triton resource exhaustion (`No valid triton configs`)

Interpretation:

- Flex Attention is not currently production-safe enough to enable by default here.
- If attention backend benchmarking resumes later, test `flash_attention_2` first
  only after installing its runtime and keeping an automatic fallback path.

## Measurement Workflow

### 1. Prepare a stored profile

```bash
curl -X POST http://127.0.0.1:8880/v1/voices/profiles \
  -F profile_id=sky \
  -F ref_audio=@/path/to/ref.wav \
  -F ref_text='Optional reference transcript.'
```

### 2. Measure the target request with curl

```bash
curl -sS -N \
  -w '\nnamelookup=%{time_namelookup} connect=%{time_connect} starttransfer=%{time_starttransfer} total=%{time_total} size=%{size_download}\n' \
  -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "This is the first sentence. And this is the second sentence streaming in.",
    "voice": "clone:sky",
    "stream": true
  }' \
  --output streaming_test.wav
```

### 3. Inspect server-side metrics

```bash
curl -s http://127.0.0.1:8880/metrics | jq
```

Important:

- `curl`'s `time_starttransfer` measures when response headers arrive.
- For FastAPI `StreamingResponse`, headers can be sent before the first PCM bytes are emitted.
- Treat `time_starttransfer` as header latency only.
- Use the server-side `streaming_ttfa_ms_*` metrics as the authoritative TTFA measurement unless the client is instrumented to detect first body bytes directly.

Key fields:

- `streaming_ttfa_ms_mean`
- `streaming_first_synthesis_ms_mean`
- `streaming_first_pcm_encode_ms_mean`
- `streaming_latest`

## Current Results

Measured on the target `clone:sky` streaming request on CUDA after Phases 2-4 were implemented.

Before these changes:

- Cold request after startup/profile save:
  - `ttfa_ms=374.1`
  - `first_clone_prompt_ms=160.3`
  - `first_cleanup_ms=75.1`
  - `total_ms=628.5`
- Immediate warm repeat:
  - `ttfa_ms=241.4`
  - `first_clone_prompt_ms=31.8`
  - `first_decode_postprocess_ms=16.9`
  - `first_cleanup_ms=75.9`
  - `total_ms=486.1`

After these changes:

- Cold request after startup/profile save:
  - `ttfa_ms=277.4`
  - `first_clone_prompt_ms=140.9`
  - `first_cleanup_ms=0.0`
  - `total_ms=415.7`
- Immediate warm repeat:
  - `ttfa_ms=129.0`
  - `first_clone_prompt_ms=0.0`
  - `first_decode_postprocess_ms=16.5`
  - `first_cleanup_ms=0.0`
  - `total_ms=267.9`

Observed impact:

- Warm TTFA improved by about `112 ms` (`241.4 -> 129.0`).
- Warm total request time improved by about `218 ms` (`486.1 -> 267.9`).
- Cached stored-profile prompts removed warm clone-prompt work entirely.
- Disabling per-request cleanup removed a consistent `~75 ms` warm-path cost.
- `curl` `time_starttransfer` remained around `2 ms`, confirming again that it is header latency, not audio TTFA.

Residual dominant buckets on the warm path:

- model-side synthesis remains the main TTFA cost
- decode/post-process is smaller but still measurable
- PCM serialization is negligible
- server-side clone prompt rebuild and cleanup are no longer meaningful warm-path costs

## Production Test Notes

Use production testing to answer these remaining questions:

1. Does disabling hot-path cleanup cause unacceptable RAM or VRAM drift over sustained traffic?
2. Does cached stored-profile prompt state remain stable across profile lifecycle events and deployment patterns?
3. Are the measured warm-path gains from local CUDA testing preserved under real request concurrency and production reference audio?
4. Do production GPUs and drivers behave differently enough that attention backend benchmarking should be revisited?

## VRAM Observability

Current understanding:

- The server does not appear to hold a large Python-side cache in VRAM.
- The largest resident components are the main OmniVoice model weights and the
  separate audio tokenizer model.
- Local inspection showed approximately:
  - core model parameters: `~1.14 GiB`
  - audio tokenizer parameters: `~0.75 GiB`
  - total loaded parameters on GPU: `~1.89 GiB`
- Cached stored-profile prompts are tiny by comparison; a typical cached prompt
  was only around `0.011 MiB` of token data.
- The larger numbers seen in `nvidia-smi` are likely to include CUDA context,
  library workspaces, and PyTorch reserved allocator memory in addition to live tensors.

New observability added:

- `/metrics` now exposes current CUDA memory counters:
  - `cuda_allocated_mb`
  - `cuda_reserved_mb`
  - `cuda_max_allocated_mb`
  - `cuda_max_reserved_mb`
  - `cuda_free_mb`
  - `cuda_total_mb`
  - `cuda_used_mb_estimate`
  - `cuda_non_torch_mb_estimate`
- `/metrics` also exposes model/component footprint and prompt-cache stats:
  - `model_core_params_mb`
  - `model_audio_tokenizer_params_mb`
  - `model_total_params_mb`
  - `prompt_cache_entries`
  - `prompt_cache_cuda_mb`
  - `prompt_cache_cpu_mb`
- `streaming_latest` now exposes first-call shape and memory drivers:
  - `first_max_condition_len`
  - `first_max_target_tokens`
  - `first_max_ref_audio_tokens`
  - `first_attention_mask_mb_estimate`
  - `first_batch_logits_mb_estimate`
  - `first_tokens_mb_estimate`
  - CUDA before/after fields for allocated, reserved, free, and total memory

Important correction:

- VRAM needs are not determined only by sentence character length.
- In OmniVoice, the first synthesis call depends on:
  - estimated target audio token count
  - reference prompt audio token count
  - combined conditioned sequence length
  - duplicated conditional/unconditional batch structure
  - dense 4D attention masks and batch logits tensors
- `stream_chunk_max_chars` is therefore only an indirect proxy for VRAM pressure.

## Immediate next implementation steps

1. Run the current build in production-like traffic and observe TTFA, VRAM, and error rates.
2. If production TTFA is still dominated by model compute, revisit CUDA attention benchmarking with explicit fallback handling.
3. Only reconsider the chunk-0 streaming-fast path if production data shows a materially larger post-process bucket than local tests did.
