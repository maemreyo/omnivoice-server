# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.5] - 2026-08-28

### Added

- **Browser UI at `/ui`** ([#36](https://github.com/maemreyo/omnivoice-server/issues/36))
  - Lists real voices from `/v1/voices` — presets, clone profiles and voice files
  - Generates and plays audio in place; separate tab for one-shot voice cloning
  - Renders the current form as a working `curl`, Python, JavaScript or OpenAI-SDK call
  - Served by default; disable with `--no-web-ui`. `/` redirects to `/ui` while enabled
  - The page loads without an API key when `--api-key` is set (there would be nowhere to type it); the endpoints it calls still require one
- **Voices defined as `.txt` files in a directory** ([#38](https://github.com/maemreyo/omnivoice-server/issues/38))
  - A file's name becomes a voice name, selectable by OpenAI-compatible clients that can only send a bare `voice` string
  - Files may pin `seed`, `speed`, `num_step`, `guidance_scale`, `t_shift`, `position_temperature`, `class_temperature`, `denoise`, `duration` and `language`, plus a `description`
  - Request parameters always win over file parameters
  - Files take precedence over built-in presets of the same name, with a startup warning
  - Validated at startup like `instructions`; an invalid file is skipped, never fatal
  - Re-read on change, so voices can be added or edited without a restart
  - New `--voice-dir` (`OMNIVOICE_VOICE_DIR`)
- **`seed` parameter** on `/v1/audio/speech` and `/v1/audio/speech/clone`, plus `--seed` as a server default. The same seed with the same text and parameters reproduces the same audio byte for byte. Bit-exact reproducibility requires `--max-concurrent 1`, since torch's RNG is process-global
- **`X-Unknown-Nonverbal-Tags`** response header naming bracketed tokens that are not recognised non-verbal symbols and were synthesized as literal text ([#37](https://github.com/maemreyo/omnivoice-server/issues/37))
- **`X-No-Speech-Detected`** response header flagging generations that contain no detectable speech, with `--no-detect-no-speech` to turn the check off

### Fixed

- **Non-verbal tags in short text produce no speech** ([#37](https://github.com/maemreyo/omnivoice-server/issues/37)). Not fixable at the server layer, but now detected and documented accurately. Measured against the real model: a single `[laughter]` fails 3/3 in a 3-word sentence and 0/3 in a 13-word one. Allow roughly 8-10 words of ordinary text per tag. The failure is a loud, steady low-frequency drone rather than silence, it is not specific to any tag, and no generation parameter avoids it — `num_step` 8/16/32 and `position_temperature=0` were each measured three times and all twelve failed. The `position_temperature=0` workaround previously recorded in `docs/verification/QA_SAMPLE_RESULTS.md` was never verified and does not work; that note has been corrected
- Zero-length generations no longer return HTTP 500. The RTF log line divided by duration inside an f-string, which is evaluated regardless of log level, so an empty result crashed on the line meant to describe it
- Streamed responses now carry `X-Unknown-Nonverbal-Tags` as well; previously only buffered responses did, contradicting the documentation
- `mypy` had been failing since numpy 2.4 shipped PEP 695 stubs, aborting before checking any project code. The type-check job now runs on the interpreter its configuration targets
- `_chunk_request` rebuilt `SynthesisRequest` field by field, silently dropping any newly added parameter from streamed requests

### Docker

- **The CPU image did not build.** `torch` was unpinned and `--index-url` replaces PyPI rather than adding to it, so pip could not resolve `flit_core`. Pinned to match CI
- **The CUDA image now builds the code under test.** It installed the server with `pip install git+...`, so every image — including release-tagged ones — contained `main` HEAD rather than the tagged code. Previously published images are affected and should be rebuilt
- CPU base image moved from `python:3.10-slim` to `python:3.12-slim`, the newest interpreter in the CI test matrix. The runtime stage copied site-packages from a hardcoded `python3.10` path, so any base bump silently broke without it
- Added `.dockerignore`; the build context previously carried `.git`, `docs` and samples

### CI

- Both Docker images are now built on any pull request that touches them. Neither was built before merge — `docker-publish.yml` only runs on `release: published` — which is why a broken CPU image went unnoticed
- `docker/*` action versions kept in step between the build and publish workflows
- `tests/test_cors.py` entered the app lifespan twice, the second time with its mocks already torn down, so every run downloaded and loaded the real 2.1GB model once per test

## [0.2.4] - 2026-05-12

### Added

- Streaming support for voice clone endpoint (`/v1/audio/speech/clone`) ([#32](https://github.com/maemreyo/omnivoice-server/issues/32))
  - New `stream` parameter (boolean, default: false) enables sentence-level streaming
  - New `response_format` parameter supports all formats (wav, pcm, mp3, opus, aac, flac)
  - Streaming mode requires `response_format='pcm'` and returns proper PCM headers
  - Proper tempdir lifecycle management ensures ref_audio exists during streaming synthesis
  - Respects global `cfg.stream` configuration for forced streaming mode

### Changed

- Extracted shared `_pcm_stream_response()` helper to reduce code duplication between `/v1/audio/speech` and `/v1/audio/speech/clone`
- Clone endpoint now supports all response formats via `tensors_to_formatted_bytes()` (previously hardcoded to WAV)

### Technical

- Added comprehensive test coverage for clone streaming (PCM headers, format validation, tempdir lifecycle, cfg.stream behavior)

## [0.2.2] - 2026-04-20

### Added

- Configurable CORS support with auth interoperability ([#24](https://github.com/maemreyo/omnivoice-server/issues/24))
  - Support for multiple origins via `CORS_ORIGINS` env var
  - Pre-flight OPTIONS handling with proper `Access-Control-Allow-Credentials`
  - Seamless integration with Bearer token authentication

### Fixed

- Voice cloning: strict validation for profile existence
  - Returns **HTTP 404** with clear error when `clone:<profile>` prefix used but profile not found ([#22](https://github.com/maemreyo/omnivoice-server/issues/22))
- `voice`/`speaker` field now correctly resolves to cloned profile when matching profile exists ([#22](https://github.com/maemreyo/omnivoice-server/issues/22))
- `profile_id` parameter in clone synthesis now respects explicitly passed profile IDs
- Windows torchcodec compatibility troubleshooting guide added to documentation

### Changed

- Dependency constraints updated in pyproject.toml for better platform compatibility

### Technical

- CI: resolved mypy and ruff lint errors
- Tests: updated voice validation assertions to match current behavior

## [0.2.1] - 2026-04-18

### Added

- Multi-speaker script synthesis endpoint (`POST /v1/audio/script`) for generating audio from multi-speaker scripts

### Fixed

- Voice cloning silently falling back to random/auto voice when using `clone:<profile>` prefix ([#22](https://github.com/maemreyo/omnivoice-server/issues/22))
  - Now returns **HTTP 404** with clear error message when profile is not found
- `voice`/`speaker` field in `/v1/audio/speech` now correctly resolves to cloned profile when a matching profile exists ([#22](https://github.com/maemreyo/omnivoice-server/issues/22))
- `profile_id` parameter in clone synthesis respects explicitly passed profile IDs
- Defensive tensor validation in script audio mixing to prevent runtime crashes
- Script endpoint validation and runtime failure path hardening
- Python 3.9 compatibility: replaced `asyncio.timeout` with `asyncio.wait_for`

## [0.2.0] - 2026-04-17

### Added

- New upstream generation parameters exposed on `/v1/audio/speech` and `/v1/audio/speech/clone`:
  - `layer_penalty_factor` (float, ≥0.0) — Layer penalty scaling factor
  - `preprocess_prompt` (bool) — Enable prompt preprocessing
  - `postprocess_output` (bool) — Enable output postprocessing (trailing silence removal)
  - `audio_chunk_duration` (float, >0.0) — Audio chunk duration threshold
  - `audio_chunk_threshold` (float, >0.0) — Audio chunk length threshold
- Instruction validation and canonicalization with upstream-aligned attribute allowlists
- Accent alias short-form expansion (e.g., `british` → `british accent`, `american` → `american accent`)
- `/v1/voices` metadata now includes `design_attributes` with canonical supported categories
- QA script (`scripts/generate_qa_samples.py`) covering baseline, new params, instruction validation, and non-verbal pass-through

### Fixed

- Reject invalid or conflicting `instructions` (duplicate gender, unsupported emotion/style, empty string)
- `/v1/audio/speech/clone` now parity-aligned with generation parameters

### Changed

- Default device changed from `cuda` to `cpu` due to Apple Silicon MPS issues (see `docs/verification/MPS_ISSUE.md`)

## [0.1.2] - 2026-04-17

### Added

- Expanded `response_format` support to all 6 OpenAI API formats: `mp3`, `opus`, `aac`, `flac`, `wav`, `pcm` ([#16](https://github.com/maemreyo/omnivoice-server/issues/16))
- Optional `pydub` dependency for format conversion (`pip install omnivoice-server[formats]`)
- Added runtime error handling with 501 Not Implemented when format conversion fails (missing pydub/ffmpeg)
- Test coverage for both `PYDUB_AVAILABLE=False` and `FFMPEG_AVAILABLE=False` scenarios

### Fixed

- Fixed BytesIO handling: replaced `torchaudio.save()` with `soundfile.write()` for WAV generation ([#15](https://github.com/maemreyo/omnivoice-server/issues/15))
- Fixed Opus MIME type: changed from incorrect `audio/opus` to `audio/ogg` (FFmpeg wraps Opus in Ogg container)
- Fixed `FFMPEG_AVAILABLE` caching: now cached at module load time for performance
- Fixed `ValueError` handling in `_convert_wav_to_format()`: moved check outside try block
- Fixed defensive access for `media_types` dict: added explicit error handling for unknown formats
- Added magic byte validation tests for MP3, Opus, AAC, and FLAC formats

### Changed

- Internal refactoring: consolidated format conversion logic in `tensors_to_formatted_bytes()`
- Audio encoding helpers are now pure functions with no side effects

## [0.1.1] - 2026-04-16

### Fixed

- Fixed CUDA device loading error: `TypeError in isnan()` when `model.generate()` returns numpy arrays instead of torch tensors ([#13](https://github.com/maemreyo/omnivoice-server/issues/13))
- Improved `_has_nan()` method in `ModelService` to handle both `torch.Tensor` and `np.ndarray` types, as well as nested lists/tuples

## [0.1.0] - 2026-04-04

### Added

- Initial release of omnivoice-server
- OpenAI-compatible TTS API (`/v1/audio/speech`)
- Three voice modes:
  - Auto: Model selects voice automatically
  - Design: Specify voice attributes (gender, age, accent, etc.)
  - Clone: Voice cloning from reference audio
- Voice profile management API (`/v1/voices/profiles`)
  - Create, read, update, delete voice cloning profiles
  - Persistent storage for reusable voice profiles
- One-shot voice cloning endpoint (`/v1/audio/speech/clone`)
- Streaming synthesis support (sentence-level chunking)
- Model listing endpoint (`/v1/models`)
- Health check endpoint (`/health`)
- Metrics endpoint (`/metrics`)
- CLI interface with `omnivoice-server` command
- Configuration via environment variables or CLI flags
- Optional Bearer token authentication
- Concurrent request handling with configurable limits
- Request timeout protection
- Audio format support: WAV and raw PCM
- Speed control (0.25x - 4.0x)
- Configurable inference steps (1-64)
- Python client examples
- cURL examples
- Streaming audio player example
- Comprehensive documentation
- CI/CD workflow with GitHub Actions

### Technical Details

- Built on FastAPI and Uvicorn
- Uses OmniVoice model from k2-fsa
- Supports CUDA, MPS, and CPU inference
- Thread pool executor for concurrent synthesis
- Pydantic-based configuration and validation
- Type hints throughout codebase
- Async/await for I/O operations

[unreleased]: https://github.com/maemreyo/omnivoice-server/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/maemreyo/omnivoice-server/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/maemreyo/omnivoice-server/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/maemreyo/omnivoice-server/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/maemreyo/omnivoice-server/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/maemreyo/omnivoice-server/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/maemreyo/omnivoice-server/releases/tag/v0.1.0
