# Verdicts: OmniVoice Library Support for Script API Ideas
**Date**: 2026-04-18  
**Scope**: Evaluate which “ideas” from `docs/reports/code-review-script-api.md` are supported directly by the upstream OmniVoice library found at `./OmniVoice/`.

**OmniVoice version (checked out locally)**: `6a3f23d` (`switch to torchaudio resampling for consistency with training`).

---

## Executive Summary

This report answers one question per idea:

1. Does OmniVoice already implement it?
2. If not, does OmniVoice expose primitives that make it easy to implement at the server layer?

**Summary**:

- **IDEA-1 (Subtitles / SRT/VTT export)**: **Not supported** by OmniVoice; requires server-side timestamping or external alignment.
- **IDEA-2 (Auto non-verbal injection)**: OmniVoice **supports non-verbal tags** in text; **auto-injection heuristics** must be implemented in the server.
- **IDEA-3 (Per-segment emotion/direction hints)**: OmniVoice supports an `instruct` channel; emotion/direction is not a first-class feature but could be attempted by mapping to `instruct`.
- **IDEA-4 (Smart pause inference)**: Not supported by OmniVoice; belongs to server orchestration/mixing.
- **IDEA-5 (Streaming output)**: OmniVoice has **chunked generation for long-form**, but **no streaming API** (it returns the full audio after completion).
- **IDEA-6 (Background ambience track)**: Not supported by OmniVoice; background mixing must be implemented outside OmniVoice.

---

## CPU vs GPU Considerations

**Context**: This evaluation assumes OmniVoice runs on CPU-only hardware.

| IDEA | CPU Feasibility | Notes |
|------|-----------------|-------|
| **IDEA-1** (Subtitles) | ✅ **Fully viable** | Server-side text processing only; no model inference |
| **IDEA-2** (Non-verbal injection) | ⚠️ **Slow but works** | Requires `model.generate()` per segment. Benchmark: RTF ~4.9 on CPU (32 steps). Use `num_step=12` or `16` for acceptable latency |
| **IDEA-3** (Emotion hints) | ⚠️ **Slow but works** | Same constraints as IDEA-2; `instruct` channel adds no overhead |
| **IDEA-4** (Smart pause) | ✅ **Fully viable** | Server-side audio mixing; no model inference |
| **IDEA-5** (Streaming) | ❌ **Not practical** | Streaming UX degrades with RTF > 1.0; each chunk takes ~5x real-time to generate |
| **IDEA-6** (Background ambience) | ✅ **Fully viable** | `pydub` audio mixing works entirely on CPU |

**Recommendation for CPU-only deployment**:
- Prioritize **IDEA-1, IDEA-4, IDEA-6** (server-side features)
- For voice synthesis features (IDEA-2, IDEA-3), use reduced diffusion steps: `num_step=12` trades ~25% quality for 2.5x speedup vs 32 steps
- Avoid **IDEA-5** streaming until GPU available or latency requirements relax

---

## IDEA-1 — Subtitle / SRT Export Alongside Audio

### Verdict
- **Status**: **NOT supported** in OmniVoice.
- **Where it belongs**: server layer.

### Evidence
- Repository-wide search for subtitle formats returns nothing meaningful:
  - No implementation for `srt`, `vtt`, `subtitle`, `caption` in `./OmniVoice` code/docs.

### Reasoning
OmniVoice produces audio from text and (optionally) reference prompts / instruct strings.
It does not provide:

- Word-level timestamps
- Token-to-time alignment
- Segment timestamps that could be turned into SRT/VTT

### What OmniVoice primitives can help?
- None directly for subtitle timestamping.
- If the server already has segment-level timestamps (e.g., from its own mixer/orchestrator), SRT/VTT is a thin formatting layer.

---

## IDEA-2 — Auto Non-Verbal Injection from Text Signals

### Verdict
- **Status**: **PARTIALLY supported**.
  - OmniVoice **supports non-verbal tags** when they are present in text.
  - OmniVoice **does not** auto-inject them.
- **Where auto-injection belongs**: server layer (`enrich_text(text)` type heuristic).

### Evidence: documentation of supported tags
OmniVoice README explicitly documents non-verbal symbols and lists supported tags:

- `./OmniVoice/README.md` (section “Non-Verbal & Pronunciation Control”)
  - Lines around `192–203` show example usage and supported tags.

### Evidence: code path that tokenizes non-verbal tags
OmniVoice builds “text tokens” via a tokenizer helper that explicitly handles non-verbal tags:

- `./OmniVoice/omnivoice/models/omnivoice.py`
  - `_prepare_inference_inputs(...)` calls `_tokenize_with_nonverbal_tags(...)` when building text tokens.
    - Lines around `1088–1097`.
  - Non-verbal tag regex and tokenizer:
    - `_NONVERBAL_PATTERN` and `_tokenize_with_nonverbal_tags(...)` at the end of the file.
    - Lines around `1505–1549`.

### Practical implication for the server
- You can safely implement `auto_nonverbals: bool` by rewriting each segment’s `text` to include tags.
- OmniVoice will tokenize these tags in a context-independent way (tags are tokenized standalone), which helps consistency across languages.

---

## IDEA-3 — Per-Segment Emotion / Direction Hints

### Verdict
- **Status**: **Support via primitive `instruct`, but no first-class “direction/emotion” feature**.
- **Best interpretation**: server can map `direction` into `instruct` (voice design prompt channel).

### Evidence: `instruct` is a first-class inference channel
OmniVoice explicitly constructs style tokens with an `instruct` section:

- `./OmniVoice/omnivoice/models/omnivoice.py`
  - `_prepare_inference_inputs(...)` builds:
    - `<|lang_start|>...<|lang_end|>`
    - `<|instruct_start|>...<|instruct_end|>`
  - Lines around `1070–1079`.

### Evidence: voice design attribute vocabulary is attribute-based
OmniVoice’s `voice_design` utilities define allowed attribute categories such as gender/age/pitch/whisper/accent/dialect:

- `./OmniVoice/omnivoice/utils/voice_design.py`
  - `_INSTRUCT_CATEGORIES` at lines around `31–46`.

### Practical implication for the server
- Implementing `direction` as a separate field is a server-level API design.
- Whether “shocked, quiet” affects output depends on how OmniVoice interprets free-form strings inside `instruct`.
  - The upstream library demonstrates normalization/validation logic for known attributes; unknown strings may or may not have effect.

---

## IDEA-4 — Smart Pause Inference from Punctuation

### Verdict
- **Status**: **NOT supported** by OmniVoice.
- **Where it belongs**: server orchestration/mixing layer.

### Evidence
- OmniVoice does include punctuation helpers for chunking and adding punctuation, but not pause timing inference:
  - `./OmniVoice/omnivoice/utils/text.py`
    - `chunk_text_punctuation(...)` and `add_punctuation(...)`.

### Practical implication for the server
- Smart pause is fundamentally a sequencing/mixing concern (especially for multi-speaker scripts).
- OmniVoice can be treated as the per-utterance synthesizer; the server decides silence timing.

---

## IDEA-5 — Streaming Output (Per-Segment Chunks)

### Verdict
- **Status**: **NOT supported as streaming**.
- **However**: OmniVoice supports **chunked generation internally** for long-form synthesis.

### Evidence: OmniVoice has long-form chunking parameters
The `generate(...)` docstring and config mention chunking controls:

- `./OmniVoice/omnivoice/models/omnivoice.py`
  - `audio_chunk_duration` and `audio_chunk_threshold` fields in `OmniVoiceGenerationConfig`.
    - Lines around `102–103`.
  - `generate(...)` docstring describes these args.
    - Lines around `520–523`.

Also documented in:

- `./OmniVoice/docs/generation-parameters.md`
  - “Long-Form Generation” section, lines around `59–67`.

### Evidence: chunked path is internal and still returns full results
- `./OmniVoice/omnivoice/models/omnivoice.py`
  - `generate(...)` chooses `_generate_chunked(...)` for long items.
    - Lines around `566–572`.
  - It still returns `generated_audios` as a list after completion.
    - Lines around `572–585`.

### Evidence: chunk outputs are merged (not streamed)
- `./OmniVoice/omnivoice/models/omnivoice.py`
  - `_decode_and_post_process(...)` uses `cross_fade_chunks(...)` to merge chunk audios.
    - Lines around `710–718`.

### Practical implication for the server
If you want HTTP streaming:

- You must implement streaming at the server layer (e.g., synthesizing segments sequentially and yielding bytes).
- Alternatively, you would need to modify OmniVoice to expose per-chunk decode outputs (not currently public API).

---

## IDEA-6 — Background Audio / Ambience Track

### Verdict
- **Status**: **NOT supported** by OmniVoice.
- **Where it belongs**: server layer (post-processing mix).

### Evidence
- OmniVoice does use `pydub.AudioSegment` in audio utilities for decoding and silence operations:
  - `./OmniVoice/omnivoice/utils/audio.py`
    - uses `AudioSegment.from_file(...)`.
- But there is no background-mixing API (e.g., `overlay`) exposed or used.

### Practical implication for the server
- Implement background ambience mixing outside OmniVoice (the server already has its own audio utilities and can mix tensors/audio bytes).

---

## Appendix: Key OmniVoice Code References (Paths)

- `./OmniVoice/omnivoice/models/omnivoice.py`
  - `OmniVoice.generate(...)`
  - `_prepare_inference_inputs(...)`
  - `_NONVERBAL_PATTERN` and `_tokenize_with_nonverbal_tags(...)`
  - `_generate_chunked(...)`
  - `_decode_and_post_process(...)`
- `./OmniVoice/omnivoice/utils/voice_design.py`
  - `_INSTRUCT_CATEGORIES` (voice design attribute sets)
- `./OmniVoice/omnivoice/utils/text.py`
  - punctuation chunking / punctuation insertion
- `./OmniVoice/docs/generation-parameters.md`
  - long-form chunking parameter docs
