# OmniVoice Streaming Improvements Plan

## Purpose

This document audits the streaming ideas originally borrowed from
[KevinAHM/echo-tts-api](https://github.com/KevinAHM/echo-tts-api) against the
actual OmniVoice architecture used by this server. It replaces the earlier
assumption that Echo-TTS block streaming can be transferred directly.

The governing rule is output safety: an optimization must preserve OmniVoice's
iterative generation, voice conditioning, chunk continuity, and postprocessing.
Ideas that rely on Echo-TTS's autoregressive/blockwise architecture are excluded
unless OmniVoice later exposes an upstream API that makes them safe.

This plan targets the Python server and the currently supported OmniVoice 0.1.x
model family. The vendored implementation is pinned to 0.1.2 for low-VRAM and
FlashInfer compatibility; the normal loader remains the default.

## Architecture Findings

### OmniVoice is not an autoregressive streaming model

OmniVoice starts with a complete masked audio-token grid and refines that grid
over `num_step` full-sequence passes. Each pass uses bidirectional attention over
the conditional and classifier-free-guidance sequences. Tokens still masked in
an intermediate pass do not represent a decodable prefix.

Consequences:

- Never decode or emit an intermediate denoising step.
- There is no stable "next token" boundary comparable to Echo-TTS.
- Autoregressive KV-cache reuse is not applicable. Changing audio tokens affect
  keys and values across the full bidirectional sequence on every pass.
- FlashInfer deliberately disables the Hugging Face KV cache and recomputes the
  packed full sequence each step.
- The first safe yield point is after `_generate_iterative()` has completed a
  whole text chunk.

### OmniVoice already has model-native long-form chunking

For text estimated above `audio_chunk_threshold`, OmniVoice splits text using
its duration estimator and `audio_chunk_duration`. Every text chunk is fully
generated before the next chunk is available.

Conditioning differs by mode:

- Clone mode conditions every chunk on the original clone prompt.
- Auto/design mode generates chunk 0 without reference audio, then uses chunk
  0's generated audio tokens and text as the fixed reference for every later
  chunk. This is important for voice consistency.
- All generated token chunks are decoded, joined with OmniVoice's boundary
  fades/silence, and postprocessed as one output.

Server-side sentence splitting is therefore not equivalent to OmniVoice's
internal long-form path. Independent auto/design calls can select a different
voice for each sentence, and independent clone calls can repeat reference
preparation unless the prompt is prepared once and reused.

### Final postprocessing is whole-output work

OmniVoice currently performs these operations after all token chunks exist:

1. Decode every chunk.
2. Join chunks with the upstream boundary algorithm.
3. Optionally remove long and edge silence over the merged waveform.
4. Apply reference RMS scaling for clone mode, or whole-output peak
   normalization for auto/design mode.
5. Apply one fade and one silence pad at the outer edges.

Whole-output silence removal and auto/design peak normalization cannot be made
exactly equivalent after earlier bytes have already been sent. A streaming
implementation must not claim non-streaming equivalence unless it either
buffers the required audio or uses an explicitly different streaming
postprocessing contract.

### Cancellation cannot interrupt an arbitrary CUDA forward safely

`run_in_executor()` cancellation stops awaiting a worker; it does not stop the
Python thread or an in-flight CUDA kernel. Safe cancellation can prevent the
next sentence or completed model chunk from starting, but it must allow the
current `_generate_iterative()` call to finish and clean up normally. Hard
thread cancellation is excluded.

## Current Server Behavior and Risks

- `/v1/audio/speech` supports sentence-level PCM streaming and explicit
  unknown-length WAV streaming. MP3 and other compressed formats remain
  buffered.
- `/v1/audio/speech/clone` currently supports PCM only when streaming.
- SSE can wrap each emitted PCM block, or each block as an independent WAV.
- `stream_overlap` is a bounded one-chunk-ahead producer queue. It does overlap
  synthesis of the next sentence with network consumption of the prior
  sentence, but it does **not** run two GPU generations concurrently.
- The standard auto/design path waits for one complete `model.generate()` call
  for the full request before yielding bytes. This preserves OmniVoice's
  chunk-0 conditioning and whole-output postprocessing.
- Long clone requests retain sentence-level HTTP chunks after preparing one
  reusable prompt for the request.
- Short adjacent clone sentences are merged up to the configured maximum
  chunk size (`stream_chunk_min_chars` defaults to 80 characters), reducing
  unnecessary outer model calls without changing OmniVoice's native chunking.
- `_chunk_request()` carries `profile_id` and a prepared `voice_clone_prompt`.
  Clone streaming prepares the prompt once before the first chunk.
- A fixed request `duration` is copied to every sentence chunk. Treating the
  whole-request duration as a per-sentence duration changes output length.
- Auto/design sentence calls do not use OmniVoice's chunk-0-as-reference rule,
  so speaker continuity is not guaranteed.

These correctness issues take priority over lower-level streaming work.

## Compatibility Decisions

| Proposal | Decision | OmniVoice-specific approach |
|---|---|---|
| Yield intermediate model steps | **Exclude: incompatible** | Intermediate masked-token grids are not complete audio and must never be decoded. |
| Model-native generation iterator | **Conditional** | Yield only after a complete internal text chunk. Feature-detect a supported OmniVoice implementation and retain sentence/non-streaming fallback. |
| Generic stateful crossfade assembler | **Replace** | Mirror OmniVoice's exact boundary algorithm. Do not apply an Echo latent-tail decoder design to independently generated waveforms. |
| Explicit disconnect cancellation | **Compatible with limits** | Stop future chunks and close iterators; let the active CUDA call finish safely. |
| `stream_overlap` / prefetch | **Keep and clarify** | Preserve one CPU-audio chunk of buffering and one GPU call at a time. Exclude concurrent adjacent GPU calls. |
| Duration-aware server chunking | **Replace** | Prefer OmniVoice's duration estimator and internal chunking. External chunking requires mode and fixed-duration safeguards. |
| Per-chunk seeds via `manual_seed` | **Exclude for now** | Global RNG mutation is unsafe with concurrent workers. Add only after OmniVoice accepts a per-request `torch.Generator`. |
| General `torch.compile` mode | **Exclude from delivery plan** | Dynamic full-sequence masks and private patched forwards make it unproven; FlashInfer CUDA graphs already cover the supported fixed-shape optimization. |
| Streaming format cleanup | **Compatible** | Keep explicit PCM/WAV contracts and buffered compressed formats; document unknown-length WAV compatibility. |
| Bounded CPU prompt cache | **Compatible, low priority** | Add count/byte bounds only if measurements show a need; preserve sidecar invalidation. |
| GPU prompt cache | **Exclude on target hardware** | Prompt tensors are small and CPU-to-GPU transfer savings do not justify persistent VRAM on an 8 GB RTX 3070. |
| Echo-style condition/KV cache | **Exclude: incompatible** | OmniVoice's bidirectional iterative refinement invalidates autoregressive KV reuse. |

## Revised Recommendations

### P0: Correct sentence-streaming semantics

Before changing model internals:

1. Prepare a clone prompt once per streaming request and reuse the CPU-resident
   prompt across all clone sentence calls. Stored profiles use the existing
   fingerprinted sidecar/cache path; one-shot references use a request-scoped
   prompt.
2. Preserve `profile_id` and `voice_clone_prompt` when deriving clone chunk
   requests. **Implemented.**
3. Do not copy a whole-request fixed `duration` to every sentence. The safe
   initial behavior is to disable sentence splitting for fixed-duration
   requests. Proportional allocation may be investigated separately, but it is
   not output-equivalent.
4. Route auto/design streaming through one complete model call until a
   model-native iterator can expose completed chunks while retaining chunk-0
   conditioning. **Implemented as the safe default.**
5. Add tests proving prompt preparation occurs once and fixed duration is not
   multiplied by the number of sentences.

This work is compatible with standard, low-VRAM, and FlashInfer modes because it
does not alter the iterative decoder.

### P0: Explicit, cooperative disconnect handling

Pass route cancellation state to the streaming coordinator and check it:

- before scheduling a sentence;
- after a completed synthesis call;
- before starting the next model-native text chunk, when that iterator exists;
- while a buffered producer waits to enqueue output.

On disconnect:

1. Stop scheduling future chunks.
2. Cancel producer/consumer tasks that have not entered inference.
3. Mark an in-flight executor future as detached and let it finish; do not
   unload modules or clear CUDA memory underneath it.
4. Release completed CPU audio tensors and temporary reference files.
5. Record cancellation separately from model errors and timeouts.

Do not attempt to kill the inference thread, raise asynchronously inside it, or
reset FlashInfer context while a forward pass is active.

### P0: Clarify and retain bounded prefetch

Rename `stream_overlap` to `stream_prefetch` with a backwards-compatible alias,
or update its description to "one-chunk-ahead output prefetch." The supported
design is:

- one active `model.generate()` call per stream;
- queue capacity of one completed CPU audio result;
- synthesis of sentence N+1 may overlap network delivery of sentence N;
- no simultaneous generation of adjacent chunks on the shared model.

This mode remains compatible with FlashInfer and low-VRAM operation when the
global inference semaphore is respected. Track the queued audio byte count to
bound host memory.

Concurrent adjacent GPU synthesis is excluded. It can interleave global RNG,
model instrumentation, FlashInfer context, and cleanup while increasing peak
VRAM on the RTX 3070.

### P1: Normalize response-format behavior

Adopt and test this contract:

- Raw HTTP PCM streams immediately with PCM metadata headers.
- Explicit raw HTTP WAV streaming uses the current unknown-length RIFF header;
  document that clients requiring finalized RIFF sizes must request buffered
  WAV instead.
- SSE `pcm` contains PCM payloads; SSE `wav` contains a complete WAV wrapper per
  event, not fragments of one WAV file.
- MP3, Opus, AAC, and FLAC remain buffered because the server does not maintain
  a stateful streaming encoder.
- The clone endpoint should either use the same WAV wrapper as the main speech
  endpoint or explicitly retain PCM-only streaming. Tests must enforce the
  selected contract.
- Forced server streaming must not silently change a requested buffered format.

The earlier claim that `/v1/audio/speech` returned PCM for an explicit WAV
stream is obsolete; the route now has a dedicated WAV stream wrapper.

### P1: Prototype an OmniVoice-native chunk iterator behind a capability gate

The only safe iterator seam is the long-form text-chunk loop:

```python
def iter_generated_token_chunks(...) -> Iterator[CompletedTokenChunk]:
    # Each yield occurs only after _generate_iterative() returns for this text chunk.
    ...
```

Requirements:

1. Preserve the original clone prompt for every clone chunk.
2. Preserve chunk 0 as the fixed reference for later auto/design chunks.
3. Preserve text chunk order, target-length estimation, RNG consumption order,
   and generation parameters.
4. Do not yield from inside the denoising-step loop.
5. Keep the non-streaming `generate()` implementation unchanged or collect the
   iterator and prove token-level equivalence.
6. Enable only when the loaded model passes an exact capability/version check.
   Unknown standard-loader versions fall back without monkey-patching private
   methods.
7. Validate standard attention, split CFG, FlashInfer, and low-VRAM separately.

Initial scope should be long-form requests that already qualify for OmniVoice
internal chunking. Short requests still produce one completed chunk and cannot
have lower model-level TTFA without changing the model architecture.

### P1: Implement boundary output only where semantics are preservable

Do not introduce a generic crossfade over sentence outputs. For model-native
chunks, implement an incremental equivalent of OmniVoice's current join:

- retain only the tail needed for the upstream fade;
- emit the finalized prior samples;
- insert the same silence interval;
- fade the next chunk head identically;
- retain the final tail until end-of-stream.

Postprocessing gates:

- Clone RMS scaling is known from the prompt and can be applied consistently.
- Outer fade/padding can be reproduced with a retained final tail.
- Whole-output silence removal must be buffered or replaced by a separately
  specified streaming algorithm; it cannot be assumed equivalent.
- Auto/design peak normalization requires the global peak. Until a stable
  streaming loudness contract is designed, use buffered postprocessing or
  retain the existing fallback for those modes.

Acceptance requires sample-level comparison of the incremental join with
OmniVoice's `cross_fade_chunks`, followed by mode-specific output tests. A
generic "boundary RMS looks acceptable" test is not sufficient to prove that
words or pauses were not damaged.

### P2: Use OmniVoice duration estimates instead of Echo heuristics

Do not add independent characters-per-second and words-per-second settings as
the primary chunker. OmniVoice already estimates target audio-token length and
derives text chunk size from frame rate and `audio_chunk_duration`.

If server-side sentence chunking remains as a fallback:

- retain punctuation and abbreviation handling;
- use the OmniVoice duration estimator when available;
- never split a fixed-duration request without an explicit allocation policy;
- reuse clone prompts;
- do not use independent auto/design calls as the quality reference;
- keep the eager first chunk optional because making it very short can reduce
  prosody and makes it the voice reference in a model-native auto/design path.

Echo-TTS's 20–40 second defaults are not adopted. OmniVoice's existing
`audio_chunk_duration=15` and `audio_chunk_threshold=30` remain the starting
point until measured on representative text and hardware.

### P2: Bound only the CPU prompt index if needed

The current profile prompt data is CPU-resident, persisted atomically in a
fingerprinted sidecar, and invalidated on profile mutation. Its tensor footprint
is small relative to model memory.

If long-running multi-tenant measurements justify a bound, add an LRU limit by
entry count and measured tensor bytes. Eviction removes only the process-local
object; the sidecar remains the source for a warm reload. Do not add a GPU prompt
cache to the RTX 3070 configuration.

## Explicitly Excluded Work

The following items must not be implemented from the Echo-TTS plan:

### Partial denoising output

Never decode token grids before all iterative unmasking steps complete. They
contain unresolved mask tokens and are not an audio prefix.

### Echo-style KV or condition-cache reuse

OmniVoice is bidirectional and changes the audio-token sequence at every
iteration. A past-key/value cache from a prior iteration is stale. Static input
assembly may be profiled, but it is not an Echo-style KV cache and should not be
described as one.

### Global or per-chunk `manual_seed`

The current implementation calls `torch.rand_like()` without a generator.
Changing the process-global CUDA RNG around concurrent executor work can couple
unrelated requests. Also, `request_seed + chunk_index` changes RNG behavior when
chunk boundaries change and cannot preserve non-streaming equivalence.

Seed support may return only after every random operation accepts a
request-scoped `torch.Generator`, including the standard and FlashInfer paths.

### Broad `torch.compile` support

Do not add a server-wide compile switch based on Echo-TTS. OmniVoice uses
dynamic sequence lengths, quadratic bidirectional masks, optional split CFG,
and private FlashInfer patches. The supported fixed-shape optimization is the
existing opt-in FlashInfer CUDA graph path. A future isolated benchmark may
reconsider compilation, but it is not an implementation phase in this plan.

### Concurrent GPU generation for adjacent chunks

Do not start two adjacent sentence/model chunks concurrently on the shared
model. This risks model-global state, RNG ordering, timing instrumentation,
FlashInfer context, cleanup races, and peak-VRAM regressions. Network/output
prefetch with one active GPU call remains allowed.

### Persistent GPU prompt cache on 8 GB cards

Prompt tensors are small and already reusable from CPU. Retaining them on GPU
has little expected latency benefit and conflicts with the low-VRAM objective.

## Metrics and Validation

Evaluate each retained optimization on the RTX 3070 target and RTX 4070 Ti
SUPER validation machine. Record:

- startup allocated/reserved VRAM;
- cold- and warm-reference peak allocated/reserved VRAM;
- TTFA and per-completed-chunk latency;
- total latency, generated duration, and real-time factor;
- queued CPU audio bytes in prefetch mode;
- boundary sample equivalence for the upstream join algorithm;
- mode-specific output similarity for clone, auto, and design;
- cancellation cleanup time and detached-worker completion time;
- prompt creation count for stored and one-shot clone streams.

Required mode matrix:

| Mode | FlashInfer | Low VRAM | Split CFG | Purpose |
|---|---:|---:|---:|---|
| Standard | No | No | No | Default architecture baseline |
| Speed | Yes | No | No | Serialized FlashInfer path |
| Low VRAM | No | Yes | Yes | RTX 3070 steady-state path |
| Fallback | Requested | Any | Yes | FlashInfer incompatibility fallback |

For model-native chunking, test clone, auto, and design independently. Matching
duration alone is not sufficient; tests must verify conditioning inputs and
generated token order. Do not claim fixed VRAM or TTFA improvements without
hardware measurements.

## Revised Delivery Order

### Phase 1: Existing-stream correctness

- Reuse one clone prompt across sentence chunks.
- Handle fixed-duration requests without multiplying duration.
- Clarify one-chunk-ahead prefetch and preserve one active GPU call.
- Add cooperative disconnect handling and cancellation metrics.
- Normalize and test PCM/WAV/compressed-format behavior.

### Phase 2: Capability-gated model chunk iteration

- Prototype yields only at completed OmniVoice text chunks.
- Preserve clone and chunk-0 auto/design conditioning exactly.
- Add collection/equivalence tests and automatic fallback.
- Validate standard, low-VRAM, split-CFG, and FlashInfer paths.

### Phase 3: Exact incremental boundary output

- Reproduce the upstream join with bounded tail retention.
- Start with clone mode and postprocessing combinations that can be preserved.
- Keep buffered/fallback behavior where global silence removal or peak
  normalization prevents equivalence.
- Benchmark TTFA and boundary quality on both NVIDIA test cards.

## Definition of Done

The retained work is complete when:

- Sentence streaming prepares a clone prompt once and handles fixed duration
  safely.
- Disconnects prevent future chunks without corrupting active model state.
- Prefetch behavior is accurately named, bounded, and never introduces a
  second simultaneous chunk generation.
- Response-format behavior is explicit and covered by tests.
- Any model-native stream yields only completed text chunks and preserves
  OmniVoice's mode-specific conditioning.
- Unsupported model versions and postprocessing combinations fall back safely.
- Standard, FlashInfer, low-VRAM, split-CFG, profile clone, one-shot clone,
  auto/design, buffered, and streaming paths pass regression tests.
- No excluded Echo-TTS optimization is presented as actionable work.
