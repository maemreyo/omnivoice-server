# Streaming and Chunking Improvements Plan

## Purpose

This plan compares the server's current streaming implementation with
[KevinAHM/echo-tts-api](https://github.com/KevinAHM/echo-tts-api) and defines the
most valuable improvements for OmniVoice.

The goal is lower time-to-first-audio (TTFA), fewer audible seams, predictable
VRAM usage, and safe cancellation for long-running requests. The plan applies
to the Python API server only; it does not propose replacing OmniVoice with
Echo-TTS's model or sampler.

## Executive Summary

The current server already has a solid HTTP streaming boundary:

- OpenAI-compatible `/v1/audio/speech` requests.
- Raw PCM streaming with audio metadata headers.
- Sentence-aware chunking and eager first-sentence emission.
- Optional producer/consumer buffering.
- Streaming metrics for TTFA, synthesis, postprocessing, and CUDA memory.
- Profile prompt caching and low-VRAM encoder lifecycle management.

The main limitation is that streaming currently happens around complete
`model.generate()` calls. OmniVoice generates a sentence or internally chunked
result before the server can emit its first PCM tensor. Echo-TTS instead exposes
an internal blockwise generator and decodes each block with retained context.

The highest-value work is therefore an OmniVoice-native generation iterator,
followed by stateful audio-boundary handling and explicit disconnect
cancellation.

## Current Server Behavior

### HTTP streaming

`/v1/audio/speech` creates a `StreamingResponse` and emits raw mono, 24 kHz,
16-bit PCM. The response includes:

- `X-Audio-Sample-Rate: 24000`
- `X-Audio-Channels: 1`
- `X-Audio-Bit-Depth: 16`
- `X-Audio-Format: pcm-int16-le`
- `X-Request-Id`

Streaming is currently intended for PCM. WAV requires a header whose final size
is not known at response start, and MP3 requires buffering or a streaming
encoder.

### Sentence streaming

The default streaming path uses
[`split_sentences()`](omnivoice_server/utils/text.py), with a configurable
maximum chunk size and an eager first chunk. Each chunk is passed through
`InferenceService.synthesize()`, and the returned tensors are converted to PCM
and yielded.

This gives useful sentence-level streaming, but each chunk still pays the full
OmniVoice generation lifecycle:

1. Prepare the request.
2. Resolve or load the voice prompt.
3. Run the complete iterative generation.
4. Decode and postprocess the generated audio.
5. Convert the result to PCM.
6. Yield the bytes.

### Long-form model chunking

The vendored OmniVoice implementation has its own long-form chunking through
`audio_chunk_duration` and `audio_chunk_threshold`. That path returns generated
chunks after generation, rather than exposing them through an async iterator.
The HTTP layer therefore cannot emit those chunks as soon as they are decoded.

### Current overlap mode

`_stream_sentences_overlapped()` uses a producer task and a bounded queue, but
the producer awaits each synthesis call before starting the next one. It
decouples generation from consumption, but it does not currently overlap GPU
inference for adjacent sentences. This is intentional for safety with shared
model state and FlashInfer, but the name and documentation should make that
distinction explicit.

## Echo-TTS Comparison

Echo-TTS's relevant implementation is in:

- [API server](https://github.com/KevinAHM/echo-tts-api/blob/main/api_server.py)
- [Blockwise inference](https://github.com/KevinAHM/echo-tts-api/blob/main/inference_blockwise.py)
- [Inference and compilation helpers](https://github.com/KevinAHM/echo-tts-api/blob/main/inference.py)
- [Repository README](https://github.com/KevinAHM/echo-tts-api#readme)

### Generation granularity

Echo-TTS generates fixed latent blocks, commonly using block sizes such as
`[32, 128, 480]`, and yields audio after each block. Its API also supports
time-sized text chunks, approximately 20–40 seconds by default.

The OmniVoice server generates per sentence at the API layer. That is simpler
and gives an early first sentence, but it cannot provide audio from inside one
long sentence or one internal OmniVoice generation call.

### Decoder continuity

Echo-TTS uses a stateful streaming decoder that retains a bounded latent tail,
decodes with context, and emits only samples that have not already been sent.
This reduces block-boundary artifacts.

The current server converts each returned tensor independently. Any fade,
padding, silence removal, or postprocessing applied to individual tensors can
therefore appear at every boundary rather than only at the final response.

### Cache reuse

Echo-TTS constructs and reuses text, speaker, and latent KV caches during
blockwise generation. The current OmniVoice path reuses voice-clone prompts,
but does not expose an equivalent public cache across iterative generation
blocks.

This is a model-internal optimization and cannot be copied mechanically. It
would require an upstream-compatible OmniVoice API or a carefully maintained
vendored patch.

### Compilation and warmup

Echo-TTS makes `torch.compile` optional, warms fixed block shapes, persists
compiler artifacts, and disables compilation after incompatible runtime
failures.

The OmniVoice upstream compile work is still experimental. Variable text
lengths, dynamic masks, and short requests can reduce or reverse the benefit.
Compilation should therefore be an explicit fixed-shape optimization, not a
default server setting.

### Disconnect handling

Echo-TTS checks whether the request is disconnected while draining its blocking
generator and closes the iterator. The current server relies primarily on
normal async-generator cancellation and does not explicitly check the client
between sentence or tensor emissions.

## Recommended Improvements

### P0: Expose an OmniVoice generation iterator

Add an internal interface with the following shape:

```python
async def generate_stream(
    request: SynthesisRequest,
) -> AsyncIterator[GeneratedAudioChunk]:
    ...
```

The blocking model implementation may remain synchronous internally, but it
must yield after each decoded audio chunk. The async service should run that
iterator in the existing executor without blocking the event loop.

Preferred implementation order:

1. Refactor the vendored OmniVoice long-form chunk loop into a generator.
2. Yield each decoded chunk before generating the next chunk.
3. Add a compatibility wrapper that collects the iterator for non-streaming
   requests.
4. Keep sentence-level streaming as the fallback for model versions that do
   not expose the chunk iterator.

The iterator must preserve voice-clone prompt reuse, low-VRAM encoder
restore/offload behavior, existing generation parameters, standard/FlashInfer
fallback, and timeout behavior.

Acceptance criteria:

- First PCM bytes are emitted before the complete response is generated.
- Non-streaming output remains numerically equivalent within existing audio
  tolerance.
- A failure after chunk N still delivers chunks 0 through N-1 and records a
  partial-stream outcome.
- The iterator closes promptly on timeout or cancellation.

### P0: Add stateful boundary handling

Create a streaming audio assembler that accepts decoded tensors and emits PCM
while retaining a bounded tail. It should:

- Keep a configurable overlap/context window.
- Avoid final silence trimming and edge padding per chunk.
- Apply crossfade only where needed.
- Apply final fade/padding once, after the last chunk.
- Preserve exact sample ordering and audio metadata.

Implement this independently of the model so it supports both the current
sentence path and the future model-native iterator.

Acceptance criteria:

- Concatenated streamed audio has no repeated padding between chunks.
- Boundary RMS discontinuities are no worse than current non-streaming output
  for representative clone and design requests.
- Final streamed duration matches non-streaming duration within tolerance.

### P0: Implement explicit disconnect cancellation

Pass request disconnect state into the streaming generator or use a
cancellation event owned by the route. Check it before each synthesis chunk,
after each generated audio chunk, and before entering the next model block.

On disconnect:

1. Stop scheduling more work.
2. Close the model iterator.
3. Cancel pending executor work where possible.
4. Release temporary audio tensors.
5. Preserve a cancellation metric distinct from model errors.

FlashInfer remains serialized; cancellation must not leave its model-global
state in a partially reused condition.

Acceptance criteria:

- A client disconnect does not start the next text/model chunk.
- GPU memory returns to the normal post-request range.
- No unhandled task warning appears in server logs.

### P1: Replace or clarify `stream_overlap`

There are two valid designs:

#### Safe buffering mode

Rename the current behavior to `stream_buffered` or document it as a producer
buffer. It remains serialized and is safe for standard inference, low-VRAM
mode, and FlashInfer.

#### Actual prefetch mode

Start synthesis of chunk N+1 while PCM from chunk N is being consumed. This
should only be enabled when model concurrency is safe, FlashInfer is disabled,
the VRAM budget has room for a second request, and cancellation can stop both
tasks.

On an 8 GB RTX 3070, actual GPU prefetch should be opt-in and benchmarked. It
may increase throughput but can increase peak VRAM and reduce single-request
latency due to contention.

### P1: Add duration-aware text chunking

Keep sentence boundaries, but add an optional target-duration chunker similar
to Echo-TTS:

- `stream_chunk_target_s`
- `stream_chunk_min_s`
- `stream_chunk_max_s`
- characters-per-second estimate
- words-per-second estimate

The first chunk should remain eager and small for TTFA. Subsequent chunks can
be merged toward a target duration to reduce repeated model setup. A sentence
longer than the maximum should fall back to word-boundary splitting.

Preserve decimal and abbreviation handling, multilingual punctuation, profile
voice consistency, and explicit speaker/design instructions. Suggested initial
defaults for OmniVoice are smaller than Echo-TTS's 20–40 second chunks until
hardware measurements justify larger values. OmniVoice's existing
`audio_chunk_duration=15` and `audio_chunk_threshold=30` provide a reasonable
starting point.

### P1: Add deterministic per-chunk seeds

Add an optional `seed` field to the request and `SynthesisRequest`. Derive each
chunk seed deterministically, for example:

```text
chunk_seed = request_seed + chunk_index
```

If no seed is supplied, retain current random behavior.

Acceptance criteria:

- Repeating the same request with the same seed produces reproducible chunks
  within the model's deterministic limits.
- Changing chunking strategy does not silently reuse the same random stream
  for every chunk.

### P1: Add fixed-shape compile mode

Add an opt-in compile setting for stable streaming shapes, with explicit
enable/disable configuration, warmup request and voice/text, artifact cache
directory and version key, optional decoder compilation, and automatic
process-local fallback after a Dynamo/Inductor failure.

Do not compile arbitrary sentence-length requests by default. Shape variation,
dynamic masks, and low request counts can make compilation slower than eager
execution.

Potential configuration:

```env
OMNIVOICE_COMPILE_STREAM=false
OMNIVOICE_COMPILE_CACHE_DIR=/var/cache/omnivoice/torchinductor
OMNIVOICE_COMPILE_WARMUP_TEXT=Hello from the streaming warmup.
```

### P2: Improve response-format semantics

Choose one explicit contract:

1. Streaming requests support PCM only; reject WAV and MP3 consistently on
   both speech endpoints.
2. PCM streams immediately, while WAV/MP3 use a buffered response and are
   emitted only after synthesis completes.

The second behavior matches Echo-TTS's documented behavior. The current
`/v1/audio/speech` route accepts WAV in one streaming branch but returns the PCM
stream response, which is ambiguous and should be corrected.

Add regression tests for PCM headers/payload, WAV behavior, MP3 behavior, and
forced server streaming configuration.

### P2: Add bounded prompt/GPU cache policy

The existing disk sidecar cache has stronger invalidation than Echo-TTS's basic
in-memory cache. The next improvement is a bounded process-local policy:

- CPU prompt cache remains the source of truth.
- Optional GPU prompt cache is disabled by default on 8 GB cards.
- LRU entries have count and byte limits.
- Profile mutation invalidates CPU and GPU entries.
- Device identity is part of GPU cache keys.

This can reduce warm-reference latency without compromising low-VRAM mode.

### P2: Investigate condition-cache reuse

Echo-TTS reuses text/speaker/latent KV caches across blockwise sampling. OmniVoice
does not currently expose a matching stable cache API in the pinned 0.1.2
implementation.

Investigate this only after the generation iterator exists. Base the work on
upstream OmniVoice APIs or a narrowly scoped vendored patch. Do not introduce a
cache that depends on mutable private tensors without invalidation and
output-equivalence tests.

## Metrics and Benchmarking

Every streaming optimization should be evaluated on the RTX 3070 target and
the available RTX 4070 Ti SUPER test machine.

Record at minimum:

- Startup allocated and reserved VRAM.
- Static audio-tokenizer parameter memory.
- Cold-reference peak allocated/reserved VRAM.
- Warm-reference peak allocated/reserved VRAM.
- TTFA.
- Per-chunk latency and real-time factor.
- Total response latency and generated duration.
- Final audio duration.
- Boundary discontinuity or crossfade measurements.
- Output similarity against non-streaming mode.
- Cancellation cleanup time.

Required test matrix:

| Mode | FlashInfer | Low VRAM | Split CFG | Purpose |
|---|---:|---:|---:|---|
| Standard | No | No | No | Baseline compatibility |
| Speed | Yes | No | No | Lowest latency path |
| Low VRAM | No | Yes | Yes | 8 GB target path |
| Fallback | Requested | Any | Yes | Missing/incompatible FlashInfer |

Use identical text, voice reference, seed, step count, and generation
parameters when comparing audio. Do not claim fixed VRAM savings without
measurements from representative hardware.

## Suggested Delivery Phases

### Phase 1: Correctness and lifecycle safety

- Fix streaming response-format semantics.
- Add explicit disconnect cancellation.
- Rename or document current buffering behavior.
- Add cancellation and boundary regression tests.

### Phase 2: Better chunk scheduling

- Add duration-aware chunking.
- Add deterministic per-chunk seeds.
- Add bounded CPU/GPU prompt cache policy.
- Extend streaming metrics to per-chunk observations.

### Phase 3: Model-native streaming

- Refactor OmniVoice generation into a yielding iterator.
- Add stateful decoded-audio assembly.
- Add a collection wrapper for non-streaming requests.
- Validate standard, low-VRAM, and FlashInfer paths.

### Phase 4: Optional fixed-shape compilation and cache reuse

- Add opt-in compilation with warmup and fallback.
- Investigate stable condition/KV cache reuse.
- Benchmark compile cache persistence and restart behavior.

## Non-Goals

- Porting Echo-TTS's diffusion sampler into OmniVoice.
- Making FlashInfer concurrent across requests.
- Enabling torch.compile by default for variable-length requests.
- Keeping all voice prompts on GPU on an 8 GB RTX 3070.
- Claiming Echo-TTS's TTFA or throughput numbers for OmniVoice without direct
  measurements.

## Definition of Done

The streaming improvement work is complete when:

- First audio is emitted from the model-native iterator before full generation
  finishes.
- Streamed and non-streamed audio have equivalent duration and acceptable
  boundary quality.
- Client disconnects stop future generation and clean up tasks and GPU state.
- WAV/MP3 behavior is explicit and covered by tests.
- Standard, FlashInfer, low-VRAM, profile-clone, one-shot-clone, and streaming
  paths all pass the existing suite.
- CUDA benchmarks report TTFA, per-chunk latency, and allocated/reserved peak
  VRAM on representative hardware.
