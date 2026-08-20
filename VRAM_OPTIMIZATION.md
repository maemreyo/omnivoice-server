# VRAM Optimization Notes

## Scope

This document summarizes the current VRAM findings for the OmniVoice server and
the most credible next steps to reduce peak GPU footprint without regressing the
streaming `clone:<profile>` production path.

Primary question:

- Why does `nvidia-smi` show roughly `6.8-7.0 GiB` for a process whose loaded
  model weights are closer to `~2 GiB`?

## Opt-in Python low-VRAM mode

Set `OMNIVOICE_LOW_VRAM_MODE=true`, `--low-vram`, or `low_vram_mode=True` to
use the vendored OmniVoice 0.1.2 loader. The setting is default-off. The normal
OmniVoice loader remains the compatibility path.

At startup, the main model is loaded in the requested FP16/BF16 mode and the
audio tokenizer is constructed from its config. Only `audio_tokenizer/model.safetensors`
keys outside `semantic_model.*`, `acoustic_encoder.*`, `encoder_semantic.*`,
`fc.*`, and `fc1.*` are loaded. Those encoder attributes are then absent from
the live tokenizer, leaving the decoder, quantizer, and synthesis components
resident.

For a cold reference, the existing encoder lock protects a short lifecycle:

1. Reconstruct the omitted encoder modules from the tokenizer config and their
   Safetensors keys.
2. Move them to the tokenizer device and encode the reference.
3. Move reusable prompt tensors to CPU and atomically write the `.tokens.pt`
   sidecar containing audio codes, RMS, transcript, source mtime, and size.
4. Remove the encoder modules, run garbage collection, and clear CUDA's cache.

A warm in-memory or valid disk sidecar hit never reconstructs the encoder. A
sidecar is invalidated when the source mtime/size or requested reference text
changes; legacy sidecars are accepted only when newer than the source audio.
Malformed, incomplete, or incompatible sidecars are ignored and regenerated.

Built-in design voices do not require the omitted reference-encoder modules.
OmniVoice's native long-form path uses generated audio-token tensors from its
first chunk as the reference for later chunks, so built-in voices remain
available in low-VRAM mode. Only uploaded-reference cloning needs the temporary
encoder-restore lifecycle described above.

This mode reduces steady-state VRAM by the size of the omitted tokenizer
encoder weights. A cold reference temporarily pays the encoder allocation and
may therefore peak above startup; the exact savings and peak depend on the
checkpoint, CUDA allocator, and hardware and must be measured with the
optional CUDA smoke test rather than assumed.

The loader is intentionally guarded. Missing model files, unsupported weight
layouts, tokenizer API changes, or generation incompatibilities are logged and
fall back to the standard OmniVoice loader. Profile cloning, one-shot cloning,
streaming, and profile invalidation use the same server API in either mode.

The implementation is Python-only. It vendors the pinned OmniVoice 0.1.2 model
source and Apache license notice under `omnivoice_server/vendor/`; it does not
use or reproduce the separate Sonorus GGUF/Vulkan architecture. Sonorus's
implementation motivated the lifecycle (decoder resident, encoder on demand,
CPU token sidecars), while this server retains its existing prompt format and
standard-loader fallback.

## Current Measured Footprint

## FlashInfer on an RTX 3070

The server now includes an opt-in FlashInfer path based on upstream OmniVoice's
July 2026 patch. Install the matching CUDA package separately, for example for
the repository's CUDA 12.8 PyTorch build:

```bash
uv pip install 'omnivoice-server[flashinfer]' \
  --extra-index-url https://flashinfer.ai/whl/cu128/
uv pip install 'flashinfer-jit-cache==0.6.15.post1+cu128' \
  --extra-index-url https://flashinfer.ai/whl/cu128/
```

Then use `--flashinfer` or `OMNIVOICE_FLASHINFER_MODE=true`. For one request at
a time, `--flashinfer-cuda-graph` can reduce launch overhead further, but it
requires more warm-up memory and is shape-sensitive. The server logs and falls
back to the regular OmniVoice forward path if FlashInfer is missing or its
private model patch does not match the installed runtime.

FlashInfer mode automatically serializes synthesis requests because its packed
attention context and CUDA-graph state are model-global; standard mode still
uses the configured `max_concurrent` value.

CUDA graphs retain static tensors and private CUDA memory pools per packed
sequence shape. The server bounds this cache to four shapes by default and
evicts older shapes with `OMNIVOICE_FLASHINFER_CUDA_GRAPH_MAX_SHAPES` or
`--flashinfer-cuda-graph-max-shapes`. This is important for workloads that
exercise many voice/text lengths; without a bound, shape diversity can consume
the remaining VRAM even though prompt tokens are CPU-resident.

For additional safety, CUDA-graph capture is disabled automatically for
reference-conditioned requests, including uploaded voice clones. Reference
lengths vary by voice and can create graph-private pools that are not fully
reclaimed after eviction on all PyTorch/CUDA combinations. These requests
still use FlashInfer's eager packed-attention path. CUDA graphs remain enabled
for reference-free design/auto requests.

For the standard (non-FlashInfer) path, `--split-cfg-batch` is an additional
opt-in memory fallback. It runs the conditional and unconditional CFG branches
as separate right-sized forwards, avoiding the padded combined `2B` tensors at
the cost of extra forward-launch overhead. FlashInfer takes precedence when
both flags are set.

On CUDA, the server prefers BF16 on Ampere-or-newer GPUs when PyTorch reports
support, then falls back to FP16 and FP32. CUDA TF32 matmul fast paths are
enabled by default and can be disabled with `--no-tf32` or
`OMNIVOICE_CUDA_TF32=false`.

When one-shot cloning omits `ref_text`, `--transcriber faster-whisper` enables
the optional CTranslate2 backend. Install it with `uv pip install
'omnivoice-server[asr]'`. The default remains the existing Transformers Whisper
path. For an 8 GB GPU, keep Faster-Whisper on CPU with `--asr-device cpu` to
avoid competing with synthesis VRAM.

The RTX 3070 is Ampere SM 8.6 and is within FlashInfer's supported architecture
range. Upstream's reported 2–2.9x result was measured on an H100, so this
project must benchmark TTFA, end-to-end latency, peak allocated/reserved VRAM,
and output equivalence on the actual 3070 before making a performance claim.
FlashInfer accelerates decoding; the low-VRAM tokenizer mode remains the
separate mechanism for removing encoder weights from steady-state VRAM.

## RTX 3070 Launch Profiles

Use the speed-oriented profile when the model fits comfortably and throughput
or latency is the priority:

```bash
uv run omnivoice-server \
  --device cuda \
  --flashinfer \
  --flashinfer-cuda-graph \
  --tf32 \
  --no-low-vram \
  --no-split-cfg-batch \
  --max-concurrent 1
```

Use the VRAM-oriented profile on an 8 GB RTX 3070 or when requests approach
the memory limit:

```bash
uv run omnivoice-server \
  --device cuda \
  --low-vram \
  --no-flashinfer \
  --split-cfg-batch \
  --tf32 \
  --max-concurrent 1
```

The speed profile keeps the standard model resident and uses FlashInfer CUDA
graphs; graphs are shape-sensitive and work best with serialized requests. The
VRAM profile unloads reference-encoder weights between cold references and
splits standard CFG forwards to reduce peak memory. Measure both profiles on
the target card with `benchmarks/run_benchmark.py` before choosing production
defaults.

Static loaded model footprint on CUDA:

- Core OmniVoice model params: `~1168.4 MB`
- Audio tokenizer params: `~764.3 MB`
- Total loaded params: `~1932.6 MB`

Prompt-cache footprint:

- Cached clone prompt token data: `~0.011 MB`

Conclusion:

- There is no large application-level VRAM cache in the server code.
- The stored profile prompt cache is negligible.

## Observed Runtime Memory

Measured after a representative long streaming `clone:sky` request:

- `cuda_allocated_mb`: `~1945.3`
- `cuda_reserved_mb`: `~5258.0`
- `cuda_max_allocated_mb`: `~4125.4`
- `cuda_max_reserved_mb`: `~5258.0`

Allocator stats from `torch.cuda.memory_stats()` on the same path:

- `allocated_bytes.all.current`: `~1945.3 MB`
- `allocated_bytes.all.peak`: `~4125.4 MB`
- `reserved_bytes.all.current`: `~5014.0 MB`
- `reserved_bytes.all.peak`: `~5014.0 MB`
- `inactive_split_bytes.all.current`: `~16.7 MB`
- `inactive_split_bytes.all.peak`: `~1154.0 MB`

Interpretation:

- The model does not keep `~5 GiB` of live tensors resident after the request.
- Peak live PyTorch allocation was still real and substantial at `~4.1 GiB`.
- Roughly `~0.9-1.1 GiB` of the peak reserve looks attributable to allocator
  overhead / fragmentation rather than active tensors.
- The larger post-request gap between `allocated` and `reserved` is reusable
  cached allocator state, not evidence of a large explicit model cache.

## Why The Working Set Is Larger Than The Weights

The current OmniVoice inference path materially expands runtime memory beyond
the static checkpoint size.

### 1. Classifier-free guidance doubles the batch

In iterative generation, OmniVoice allocates tensors for both conditional and
unconditional branches:

- [`omnivoice.py`](/home/remo/github/omnivoice-server/.venv/lib/python3.12/site-packages/omnivoice/models/omnivoice.py#L1162)
- [`omnivoice.py`](/home/remo/github/omnivoice-server/.venv/lib/python3.12/site-packages/omnivoice/models/omnivoice.py#L1178)

That means the hot path uses `2 * B` for several sequence-shaped tensors.

This is not waste when `guidance_scale > 0`, but it is a real VRAM multiplier.

### 2. Full-sequence forward passes happen on every iterative decode step

Generation repeatedly runs the full model over the current sequence:

- [`omnivoice.py`](/home/remo/github/omnivoice-server/.venv/lib/python3.12/site-packages/omnivoice/models/omnivoice.py#L1226)

There is no KV-cache-style reuse here. The model re-materializes activations and
uses CUDA library workspace across multiple decoding steps.

### 3. Sequence length is driven by audio-token generation, not only text length

For the measured first streamed chunk:

- `first_chunk_chars`: `68`
- `first_max_condition_len`: `597`
- `first_max_target_tokens`: `396`
- `first_max_ref_audio_tokens`: `175`

This is why a short sentence can still create a nontrivial GPU working set.

### 4. Some tensor work is wasteful, but not multi-GB wasteful

The model computes full-sequence logits:

- [`omnivoice.py`](/home/remo/github/omnivoice-server/.venv/lib/python3.12/site-packages/omnivoice/models/omnivoice.py#L405)

Then upcasts them to fp32:

- [`omnivoice.py`](/home/remo/github/omnivoice-server/.venv/lib/python3.12/site-packages/omnivoice/models/omnivoice.py#L1231)

Only the target slices are consumed later:

- [`omnivoice.py`](/home/remo/github/omnivoice-server/.venv/lib/python3.12/site-packages/omnivoice/models/omnivoice.py#L1240)

For the measured shape, rough tensor-size estimates are:

- dense attention mask: `< 1 MB`
- full fp32 logits tensor: `~37 MB`
- one layer of fp16 attention scores: `~22 MB`

So there is some obvious inefficiency, but not enough to explain the entire
`~7 GiB` seen in `nvidia-smi`.

## Bottom Line

Current evidence suggests:

- No large explicit VRAM cache in server code
- Real peak inference demand around `~4.1 GiB`
- Additional `~1 GiB` class overhead from allocator fragmentation / reserve
- Remaining difference in `nvidia-smi` likely includes CUDA context and library
  workspace outside the directly attributed PyTorch tensor footprint

So the `~7 GiB` process size is higher than the model weights alone, but it is
not mostly fake or obviously wasted by the application.

## Recommendations

### 0. Persist and offload voice-reference state

The server now applies the lowest-risk part of Sonorus's voice lifecycle:

- Stored profile prompts are persisted beside the reference WAV as
  `ref_audio.tokens.pt` after the first successful encoding.
- Prompt tokens are kept CPU-resident between requests and moved to the model
  device only during generation.
- On compatible OmniVoice builds, the server requests `skip_encoder=True`.
  Older builds automatically fall back to the standard loader.
- When the installed tokenizer exposes the expected encoder modules, those
  modules are moved to CPU between reference preparations and restored only for
  a cache miss.

This reduces repeated reference encoding and avoids retaining cached voice
tokens in VRAM. It does not by itself reproduce Sonorus's full ~600 MB saving:
that requires a patched OmniVoice loader that can omit the encoder weights at
startup and reload only those weights on demand. The current upstream Python
package does not provide that API.

### 1. Lowest-risk next experiment: allocator tuning

Best first test:

```bash
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

Why:

- This workload has varying sequence lengths and chunk sizes.
- Peak `inactive_split_bytes` was high enough to suggest fragmentation.
- This setting is intended for workloads with changing allocation sizes.

Expected upside:

- Reduce allocator slivers / fragmented reserve
- Potentially reclaim on the order of `~1 GiB` of peak reserve

Expected risk:

- Low integration risk
- Low code risk
- Performance impact must still be benchmarked, but this is the cleanest first
  allocator experiment

### 2. Medium-value model-path optimization: CFG fast path for `guidance_scale=0`

If the server ever runs with `guidance_scale=0`, the unconditional branch should
be skipped entirely instead of still allocating the doubled batch.

This would reduce real peak memory, not only reserve.

### 3. Medium-value model-path optimization: avoid unnecessary full fp32 logits

If upstream can avoid materializing or keeping the full fp32 logits tensor for
all positions, there is a modest VRAM reduction available.

This is likely a tens-of-MB optimization, not a multi-GB one.

### 4. Largest durable reduction: quantize the core model

If allocator tuning is insufficient and the tokenizer must remain on GPU,
quantizing the core model is the most credible next large memory reduction.

Most likely order:

1. int8 core model
2. fp8 benchmark only if int8 is insufficient
3. 4-bit only as a more experimental path

## Recommended Test Plan

1. Baseline current production-like run with `/metrics` and `torch.cuda.memory_stats()`.
2. Restart server with:

```bash
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

3. Compare:

- `cuda_max_allocated_mb`
- `cuda_max_reserved_mb`
- `inactive_split_bytes.all.peak`
- streaming TTFA
- total streaming latency

If reserve drops materially and latency stays flat, keep it. If not, revert and
move on to true peak reducers such as model-path changes or quantization.

## Current Allocator Tuning Result

Status: implemented and tested.

Server change:

- The server now applies `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` by
  default on CUDA startup.
- It can be disabled for A/B testing with `OMNIVOICE_CUDA_ALLOC_CONF=off` or
  `--cuda-alloc-conf off`.

Measured A/B on the same long streaming `clone:sky` request:

- Baseline, allocator override disabled:
  - `cuda_max_allocated_mb`: `4125.4`
  - `cuda_max_reserved_mb`: `5258.0`
  - `streaming_ttfa_ms`: `350.6`
  - `streaming_total_ms`: `2375.3`
- With `expandable_segments:True` enabled:
  - `cuda_max_allocated_mb`: `4089.3`
  - `cuda_max_reserved_mb`: `4100.0`
  - `streaming_ttfa_ms`: `338.5`
  - `streaming_total_ms`: `2607.0`

Interpretation:

- Peak reserved VRAM dropped by about `1158 MB`.
- Peak allocated VRAM changed only slightly.
- TTFA stayed effectively flat within normal run-to-run variance.
- Total request time moved around, but there is no evidence here of a clear
  latency regression caused by the allocator setting.

Current recommendation:

- Keep `expandable_segments:True` enabled by default on CUDA.
- Recheck under production concurrency, but this is currently the best
  low-risk VRAM improvement found.
