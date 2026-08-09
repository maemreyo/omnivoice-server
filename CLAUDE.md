# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An OpenAI-compatible FastAPI HTTP server wrapping the upstream `omnivoice` Python package (k2-fsa/OmniVoice TTS). It adds **no ML capability** — only HTTP surface, concurrency control, persistent voice profiles, streaming, and observability. Published to PyPI as `omnivoice-server`.

PyTorch is **not** a declared dependency — users must install torch/torchaudio themselves before installing this package (CI installs the CPU wheels explicitly).

## Commands

```bash
make dev            # pip install -e ".[dev]"
make test           # pytest tests/ -v
make test-cov       # + coverage (term-missing + htmlcov/)
make lint           # ruff check omnivoice_server/ tests/
make format         # ruff format
make type-check     # mypy omnivoice_server/
make docker-build / docker-run / docker-stop

pytest tests/test_streaming.py -v                    # single file
pytest tests/test_speech.py::test_name -v            # single test
```

`make` defaults to `PY ?= python3.11`; override with `make test PY=python3.12`.

Releases are fully automated: `make release RELEASE_VERSION=0.3.0` (or `release-patch`/`-minor`/`-major`) bumps `pyproject.toml` **and** `omnivoice_server/__init__.py`, commits, tags, pushes, and creates the GitHub release — which triggers the PyPI and Docker publish workflows. Update `CHANGELOG.md` before releasing. Never bump versions by hand in only one of the two files.

CI (`.github/workflows/ci.yml`) runs ruff, mypy, and pytest on Python 3.10/3.11/3.12. `ffmpeg` is installed in CI because format-conversion tests need it.

## Architecture

Request flow: `cli.py` (argparse → `Settings`) → `app.py::create_app` → routers → services → upstream `omnivoice`.

**All shared state lives on `app.state`, set up in the `lifespan` context manager — there are no module-level globals.** Routers reach state through `Depends(_get_*)` helpers that read `request.app.state`. Follow this pattern when adding services.

### Concurrency model (read before touching `services/inference.py`)

The model is a single in-process singleton, so uvicorn must run `workers=1`. Inference is blocking, so it runs in a `ThreadPoolExecutor(max_workers=cfg.max_concurrent)` gated by an `asyncio.Semaphore(cfg.max_concurrent)` of the same size. Excess requests queue in the event loop rather than being rejected, until `request_timeout_s` produces a 504. `_cleanup_memory()` runs in a `finally` on every inference (gc + `empty_cache`) to mitigate Torch memory growth.

### The upstream seam

`OmniVoiceAdapter` in [omnivoice_server/services/inference.py](omnivoice_server/services/inference.py) is the **single** place that builds `model.generate()` kwargs. When upstream adds or renames a parameter, change `build_kwargs()` only — not the Pydantic request models, not the routers. It also catches `TypeError` from `generate()` and retries with a minimal kwarg set. The `omnivoice` dependency is pinned to `>=0.2.1,<0.3.0` because upstream is new and still moving.

Upstream `generate()` names only `text`, `language`, `ref_text`, `ref_audio`, `voice_clone_prompt`, `instruct`, `duration`, `speed`, `generation_config`, `normalize_text` — everything else (`num_step`, `guidance_scale`, `denoise`, `t_shift`, temperatures, `layer_penalty_factor`, `pre/postprocess_*`, `pad_duration`, `fade_duration`, `audio_chunk_*`) reaches `OmniVoiceGenerationConfig` through `**kwargs`. That passthrough is what lets `build_kwargs()` stay a flat dict; if upstream ever drops it, this adapter is the only thing that has to change. Note the parameter is `language`, **not** `language_id` (the upstream README uses the wrong name in places).

Optional params use `None` to mean "use the server default", resolved in `build_kwargs()` against `Settings`. Adding a tunable means touching: `Settings` (default) → `cli.py` (flag) → request model (per-request override) → `SynthesisRequest` → `build_kwargs()` → **`_chunk_request()` in `speech.py`**. That last one is easy to miss and fails silently: streaming rebuilds a fresh `SynthesisRequest` per sentence, so any field omitted there is dropped only on the streaming path.

Resolve overrides with `is not None`, never truthiness — `pad_duration=0.0` and `speed=0.0`-style values are meaningful settings, not "unset".

### Voice resolution

`_resolve_synthesis_mode()` in [omnivoice_server/routers/speech.py](omnivoice_server/routers/speech.py) collapses `speaker` / `voice` / `instructions` into one of two modes: `design` (a text attribute prompt) or `clone` (a stored profile's ref audio). Precedence: clone profile lookup → `instructions` → `speaker` preset → `voice` preset → `voice` as free-form design attributes → default. Conflicting `speaker`+`voice` and unrecognized values raise 422 rather than silently falling back; `clone:<id>` with a missing profile raises 404.

Design attribute vocabulary lives in [omnivoice_server/voice_presets.py](omnivoice_server/voice_presets.py) (`DESIGN_ATTRIBUTES`, `OPENAI_VOICE_PRESETS`) and is validated/canonicalized by [omnivoice_server/utils/instruction_validation.py](omnivoice_server/utils/instruction_validation.py). The model supports gender/age/pitch/accent/dialect only — emotion and speaking-style words are **explicitly rejected**, not ignored. Add a new attribute to `DESIGN_ATTRIBUTES`, not to ad-hoc string checks.

The OpenAI voice names (`alloy`, `nova`, …) are local heuristic design prompts, not real voice clones.

### Endpoints

| Route | Notes |
|---|---|
| `POST /v1/audio/speech` | OpenAI-compatible TTS |
| `POST /v1/audio/speech/clone` | one-shot cloning, multipart upload |
| `POST /v1/audio/script` | multi-speaker script; `single_track` (mixed) or `multi_track` (base64 per speaker), `on_error: abort\|skip` |
| `GET /v1/voices`, CRUD `/v1/voices/profiles[/{id}]` | persistent clone profiles on disk |
| `GET /v1/models[/{id}]`, `GET /health`, `GET /metrics` | unauthenticated even when `api_key` is set |

Streaming is sentence-level: `split_sentences()` chunks the input and each chunk is synthesized independently, so **streaming only supports `response_format="pcm"`** (a WAV header can't be written before total length is known) and voice can drift between chunks. Once bytes have been sent, errors truncate the stream silently — no HTTP status can be changed. `cfg.stream_overlap` swaps the serial generator for a producer/consumer queue variant.

Profiles are directories under `cfg.profile_dir` containing `ref_audio.wav` + `meta.json`; IDs are constrained to `^[a-zA-Z0-9_-]{1,64}$` at both the API and storage layers.

### Configuration

`Settings` (pydantic-settings) is the single source of truth. Env prefix is `OMNIVOICE_` and `.env` is read. Precedence: CLI flags > env > defaults. `device="auto"` resolves via a `field_validator` that imports torch lazily; `cors_allow_credentials=True` with `"*"` origins is rejected at validation time.

## Testing

`tests/conftest.py` patches `ModelService.load` and `is_loaded`, then replaces `app.state.inference_svc.synthesize` with an `AsyncMock` returning 1s of silence. **Tests never load the real model or hit a GPU** — keep it that way. Use `make_wav_bytes()` / `make_silence_tensor()` from conftest for audio fixtures. `asyncio_mode = "auto"`, so async tests need no marker.

## Conventions

- Line length 100; ruff (`E,F,I,N,W,UP`) + ruff-format + mypy (non-strict) via pre-commit (`make pre-commit-install`).
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
- Errors go through the global handlers in `app.py`, which wrap everything as `{"error": {"code", "message"}}` with codes from `_status_to_code`.
- Voice-resolution paths log with a `[TRACE]` prefix — that convention is load-bearing for debugging the mode decision tree; preserve it when editing those functions.

## Known upstream defects

- **End-of-sentence truncation** ([#245](https://github.com/k2-fsa/OmniVoice/issues/245), open as of 0.2.1): the tail of generated audio gets clipped. Mitigate with `pad_duration` (0.2–0.3) so the clip lands in padding, and/or higher `guidance_scale`. Do not "fix" this by trimming more audio.
- **Dropped phoneme before `,` / `.`** ([#116](https://github.com/k2-fsa/OmniVoice/issues/116)): **closed**, fixed by the punctuation-handling fix in upstream 0.2.0. Don't re-add the old "insert a space before punctuation" workaround — on a fixed build it just injects wrong prosody.
- `postprocess_output=True` (upstream default) already **trims trailing silence** from output. Any silence trimming this server adds stacks on top of that, which is how you turn a padding problem into a clipping problem.

## Platform status

CPU and CUDA work. **MPS (Apple Silicon) is broken** — `ModelService` falls through float16 → bfloat16 → float32, running a 4-step sanity generate and rejecting any dtype that produces NaN, but MPS still fails; use `--device cpu` on Mac. See [docs/verification/MPS_ISSUE.md](docs/verification/MPS_ISSUE.md).

Non-WAV/PCM formats (mp3, opus, aac, flac) need the `formats` extra (pydub) **and** system ffmpeg; without them the endpoints return 501. `FFMPEG_AVAILABLE` is probed once at module import.

## Docs worth reading

- [docs/architecture/overview.md](docs/architecture/overview.md) — mermaid diagrams for concurrency, request lifecycles, voice decision tree, error taxonomy
- [docs/design/dataflow.md](docs/design/dataflow.md), [docs/system/specification.md](docs/system/specification.md)
- [docs/readme/sections/](docs/readme/sections/) — README is a thin index over these numbered section files; edit the section file, not the README body
