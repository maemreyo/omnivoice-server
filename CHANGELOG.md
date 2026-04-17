# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[unreleased]: https://github.com/maemreyo/omnivoice-server/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/maemreyo/omnivoice-server/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/maemreyo/omnivoice-server/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/maemreyo/omnivoice-server/releases/tag/v0.1.0
