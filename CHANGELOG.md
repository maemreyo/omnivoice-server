# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[unreleased]: https://github.com/maemreyo/omnivoice-server/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/maemreyo/omnivoice-server/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/maemreyo/omnivoice-server/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/maemreyo/omnivoice-server/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/maemreyo/omnivoice-server/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/maemreyo/omnivoice-server/releases/tag/v0.1.0
