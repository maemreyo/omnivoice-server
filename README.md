# omnivoice-server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/maemreyo/omnivoice-server/actions/workflows/ci.yml/badge.svg)](https://github.com/maemreyo/omnivoice-server/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/omnivoice-server.svg)](https://pypi.org/project/omnivoice-server/)

OpenAI-compatible HTTP server for [OmniVoice](https://github.com/k2-fsa/OmniVoice) text-to-speech.

**Author:** zamery ([@maemreyo](https://github.com/maemreyo)) | **Email:** matthew.ngo1114@gmail.com

> **⚠️ Early Development Notice**
>
> This is a new repository built on top of OmniVoice (released 2026). Both the upstream model and this server wrapper are under active development. Expect:
> - API changes and breaking updates
> - Performance improvements as PyTorch MPS support matures
> - New features and bug fixes
> - Documentation updates
>
> **Current Status**: Functional on CPU and CUDA. MPS (Apple Silicon) has known issues. See [Verification Status](#️-verification-status) below.

## Features

- **OpenAI-compatible API** - Drop-in replacement for OpenAI TTS endpoints
- **Three voice modes**:
  - **Auto**: Model selects voice automatically
  - **Design**: Specify voice attributes (gender, age, accent, pitch, style)
  - **Clone**: Voice cloning from reference audio
- **Voice profile management** - Save and reuse cloned voices
- **Streaming synthesis** - Low-latency sentence-level streaming
- **Concurrent requests** - Configurable thread pool for parallel synthesis
- **Dynamic batching** - Groups concurrent requests into single GPU calls for higher throughput
- **In-memory audio cache** - LRU cache with TTL for repeated requests (same voice + text)
- **Multiple audio formats** - WAV and raw PCM output
- **Speed control** - 0.25x to 4.0x playback speed
- **Optional authentication** - Bearer token support
- **Production-ready** - Request timeouts, health checks, metrics

## Quick Start

### Prerequisites

**PyTorch must be installed before installing omnivoice-server.** The correct PyTorch variant depends on your hardware:

```bash
# CPU only (works everywhere, but slow)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# NVIDIA GPU (CUDA) - recommended for production
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

# Apple Silicon (MPS) - currently broken, use CPU instead
# See docs/verification/MPS_ISSUE.md for details
```

For other CUDA versions or more options, see the [official PyTorch installation guide](https://pytorch.org/get-started/locally/).

### Installation

```bash
# Option 1: Install from PyPI (recommended)
pip install omnivoice-server

# Option 2: Install with uv (faster)
uv tool install omnivoice-server

# Option 3: Install from GitHub (latest development version)
pip install git+https://github.com/maemreyo/omnivoice-server.git

# Option 4: Clone and install locally for development
git clone https://github.com/maemreyo/omnivoice-server.git
cd omnivoice-server
pip install -e .
```

### Start the Server

```bash
# Basic usage (downloads model on first run)
omnivoice-server

# With custom settings
omnivoice-server --host 0.0.0.0 --port 8880 --device cuda

# With authentication
export OMNIVOICE_API_KEY="your-secret-key"
omnivoice-server
```

The server will start at `http://127.0.0.1:8880` by default.

## ⚠️ Verification Status

**Last Updated**: 2026-04-04
**Status**: ✅ Working (CPU only)

### Quick Summary

- ✅ **System works** - Produces clear, high-quality audio for English and Vietnamese
- ❌ **MPS broken** - Apple Silicon GPU has PyTorch bugs, use CPU instead
- ⚠️ **CPU slow** - RTF=4.92 (5x slower than real-time, ~10s per voice)
- ✅ **No memory leaks** - Stable memory usage verified

### Benchmark Results (CPU)

| Metric | Value | Status |
|--------|-------|--------|
| Latency (mean) | 10.2 seconds | ⚠️ Slow |
| RTF (Real-Time Factor) | 4.92 | ⚠️ 5x slower than real-time |
| Memory leak | None | ✅ Stable |
| Audio quality | Excellent | ✅ Clear speech |

### Production Recommendation

**For production, deploy on NVIDIA GPU (CUDA):**
- 20-25x faster than CPU (RTF~0.2)
- Cloud options: AWS g5.xlarge (~$1/hr), GCP T4/V100, RunPod (~$0.40/hr)

**Detailed reports**: See [`docs/verification/`](./docs/verification/) for full verification results and technical details.

### Audio Samples

Listen to verified voice samples:

**English (Female, American accent)** - 199KB

[Download English sample](https://github.com/maemreyo/omnivoice-server/releases/download/v0.1.0/test_english.wav)

**Vietnamese (Female)** - 203KB

[Download Vietnamese sample](https://github.com/maemreyo/omnivoice-server/releases/download/v0.1.0/test_vietnamese.wav)

Both samples demonstrate clear, natural speech quality on CPU device.

### First Request

```bash
curl -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "Hello, this is OmniVoice text-to-speech!",
    "voice": "auto"
  }' \
  --output speech.wav
```

## API Usage

### Basic Synthesis

```python
import httpx

response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "model": "omnivoice",
        "input": "Hello world!",
        "voice": "auto",
        "response_format": "wav"
    }
)

with open("output.wav", "wb") as f:
    f.write(response.content)
```

### Voice Design

Specify voice attributes to design a custom voice:

```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "model": "omnivoice",
        "input": "This voice has specific attributes.",
        "voice": "design:female,british accent,young adult,high pitch"
    }
)
```

Available attributes:
- **Gender**: male, female
- **Age**: child, young adult, middle-aged, elderly
- **Pitch**: very low, low, medium, high, very high
- **Style**: whisper
- **Accent (English)**: American, British, Australian, Indian, Irish
- **Dialect (Chinese)**: 四川话, 陕西话, 粤语, 闽南话

### Voice Cloning

#### Option 1: Save a Profile (Reusable)

```python
# Create a profile
with open("reference.wav", "rb") as f:
    response = httpx.post(
        "http://127.0.0.1:8880/v1/voices/profiles",
        data={
            "profile_id": "my_voice",
            "ref_text": "This is the reference text."
        },
        files={"ref_audio": f}
    )

# Use the profile
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "model": "omnivoice",
        "input": "This uses my cloned voice.",
        "voice": "clone:my_voice"
    }
)
```

#### Option 2: One-Shot Cloning

```python
with open("reference.wav", "rb") as f:
    response = httpx.post(
        "http://127.0.0.1:8880/v1/audio/speech/clone",
        data={
            "text": "This is one-shot cloning.",
            "ref_text": "Reference text."
        },
        files={"ref_audio": f}
    )
```

### Streaming

Stream audio in real-time for lower latency:

```python
with httpx.stream(
    "POST",
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "model": "omnivoice",
        "input": "Long text to stream...",
        "voice": "auto",
        "stream": True
    }
) as response:
    for chunk in response.iter_bytes():
        # Process PCM audio chunks
        play_audio(chunk)
```

See `examples/streaming_player.py` for a complete example.

## CLI Usage

```bash
# Start server with defaults
omnivoice-server

# Custom host and port
omnivoice-server --host 0.0.0.0 --port 8880

# Use GPU
omnivoice-server --device cuda

# Adjust inference quality (higher = better quality, slower)
omnivoice-server --num-step 32

# Enable authentication
omnivoice-server --api-key your-secret-key

# Adjust concurrency
omnivoice-server --max-concurrent 4

# Custom model path
omnivoice-server --model-id /path/to/local/model
```

### Environment Variables

All CLI options can be set via environment variables with `OMNIVOICE_` prefix:

```bash
export OMNIVOICE_HOST=0.0.0.0
export OMNIVOICE_PORT=8880
export OMNIVOICE_DEVICE=cuda
export OMNIVOICE_API_KEY=your-secret-key
export OMNIVOICE_NUM_STEP=32
export OMNIVOICE_MAX_CONCURRENT=4

omnivoice-server
```

## Configuration

| Option | Env Var | Default | Description |
|--------|---------|---------|-------------|
| `--host` | `OMNIVOICE_HOST` | `127.0.0.1` | Bind host |
| `--port` | `OMNIVOICE_PORT` | `8880` | Bind port |
| `--device` | `OMNIVOICE_DEVICE` | `cpu` | Device: cpu, cuda (MPS broken) |
| `--num-step` | `OMNIVOICE_NUM_STEP` | `32` | Inference steps (1-64, higher=better quality) |
| `--max-concurrent` | `OMNIVOICE_MAX_CONCURRENT` | `2` | Max concurrent requests (or batch dispatches) |
| `--batch-enabled` | `OMNIVOICE_BATCH_ENABLED` | `true` | Enable dynamic batching of concurrent requests |
| `--batch-max-size` | `OMNIVOICE_BATCH_MAX_SIZE` | `8` | Max requests per batch |
| `--batch-timeout-ms` | `OMNIVOICE_BATCH_TIMEOUT_MS` | `50` | Batch accumulation timeout in ms |
| `--api-key` | `OMNIVOICE_API_KEY` | `""` | Bearer token (empty = no auth) |
| `--cache-enabled` | `OMNIVOICE_CACHE_ENABLED` | `true` | Enable in-memory audio cache |
| `--cache-max-mb` | `OMNIVOICE_CACHE_MAX_MB` | `512` | Max cache memory in MB (LRU eviction) |
| `--cache-ttl-s` | `OMNIVOICE_CACHE_TTL_S` | `3600` | Cache entry TTL in seconds (0 = no expiry) |
| `--model-id` | `OMNIVOICE_MODEL_ID` | `k2-fsa/OmniVoice` | HuggingFace repo or local path |
| `--profile-dir` | `OMNIVOICE_PROFILE_DIR` | `~/.omnivoice/profiles` | Voice profiles directory |
| `--log-level` | `OMNIVOICE_LOG_LEVEL` | `info` | Logging level |

## API Reference

### Endpoints

#### `POST /v1/audio/speech`

Generate speech from text (OpenAI-compatible).

**Request body:**
```json
{
  "model": "omnivoice",
  "input": "Text to synthesize",
  "voice": "auto",
  "response_format": "wav",
  "speed": 1.0,
  "stream": false,
  "num_step": 32
}
```

**Response:** Audio file (WAV or PCM)

#### `POST /v1/audio/speech/clone`

One-shot voice cloning (multipart form).

**Form fields:**
- `text` (required): Text to synthesize
- `ref_audio` (required): Reference audio file
- `ref_text` (optional): Reference transcript
- `speed` (optional): Playback speed (default: 1.0)
- `num_step` (optional): Inference steps

**Response:** Audio file (WAV)

#### `GET /v1/voices`

List available voices and profiles.

**Response:**
```json
{
  "voices": [
    {"id": "auto", "type": "auto", "description": "..."},
    {"id": "design:<attributes>", "type": "design", "description": "..."},
    {"id": "clone:my_voice", "type": "clone", "profile_id": "my_voice"}
  ],
  "design_attributes": {...},
  "total": 3
}
```

#### `POST /v1/voices/profiles`

Create a voice cloning profile.

**Form fields:**
- `profile_id` (required): Unique identifier (alphanumeric, dashes, underscores)
- `ref_audio` (required): Reference audio file
- `ref_text` (optional): Reference transcript
- `overwrite` (optional): Overwrite existing profile (default: false)

**Response:**
```json
{
  "profile_id": "my_voice",
  "created_at": "2026-04-04T12:00:00Z",
  "ref_text": "Reference text"
}
```

#### `GET /v1/voices/profiles/{profile_id}`

Get profile details.

#### `PATCH /v1/voices/profiles/{profile_id}`

Update profile (ref_audio and/or ref_text).

#### `DELETE /v1/voices/profiles/{profile_id}`

Delete a profile.

#### `GET /v1/models`

List available models (OpenAI-compatible).

#### `GET /health`

Health check endpoint.

#### `GET /metrics`

Prometheus-style metrics (includes cache stats when enabled).

#### `DELETE /v1/audio/cache`

Clear the in-memory audio cache. Returns cache stats at the moment of clearing.

## Advanced Features

### Dynamic Batching

When multiple requests arrive concurrently, the server groups them into a single `model.generate()` call using OmniVoice's native batch API. This improves GPU utilisation and throughput under load — a batch of 8 requests takes roughly the same time as 2-3 individual calls.

Requests are grouped by compatible generation parameters (num_step, guidance_scale, etc.). Per-item parameters like text, voice, speed, and duration vary freely within a batch.

```bash
# Tune batching behaviour
omnivoice-server --batch-max-size 8 --batch-timeout-ms 50

# Disable batching (legacy single-request mode)
omnivoice-server --no-batch
```

The batch dispatches when either `batch_max_size` is reached or `batch_timeout_ms` elapses since the first request in the batch. Batch stats (dispatches, avg size) are available on `/metrics`.

If the batched call fails (e.g. upstream API change), it falls back to sequential single-item generation automatically.

### Audio Cache

Repeated requests with the same parameters (voice, text, speed, etc.) are served from an in-memory LRU cache, skipping inference entirely. This is useful when clients send the same request many times (e.g. the same clone profile + text).

The cache stores final audio bytes (WAV/PCM), not GPU tensors, so it doesn't consume GPU memory.

```bash
# Check cache stats
curl http://127.0.0.1:8880/metrics
# → { "cache_hits": 42, "cache_misses": 10, "cache_hit_rate": 0.808, ... }

# Clear the cache
curl -X DELETE http://127.0.0.1:8880/v1/audio/cache

# Disable cache entirely
omnivoice-server --no-cache
```

Responses include an `X-Cache: HIT` or `X-Cache: MISS` header. Cache applies to non-streaming `/v1/audio/speech` only — streaming and one-shot `/v1/audio/speech/clone` are not cached.

Memory is managed by:
- **LRU eviction**: when total cached bytes exceed `cache_max_mb` (default 512MB), least-recently-used entries are dropped.
- **TTL expiry**: a background sweep removes entries older than `cache_ttl_s` (default 3600s). Set to 0 to disable TTL (LRU-only).

### Non-Verbal Symbols

OmniVoice natively supports non-verbal symbols inline in text. These are pass-through features from the upstream model:

```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "input": "Hello [laughter] this is amazing [breath] really cool [sigh]",
        "voice": "auto"
    }
)
```

Supported symbols:
- `[laughter]` - Natural laughter
- `[breath]` - Breathing sound
- `[sigh]` - Sighing sound
- Other non-verbal expressions supported by OmniVoice

### Pronunciation Correction

For Chinese text, you can provide pinyin hints for pronunciation correction:

```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "input": "这是拼音(pīn yīn)提示的例子",
        "voice": "auto"
    }
)
```

The server passes these hints directly to OmniVoice without modification.

### Advanced Generation Parameters

Fine-tune synthesis quality and characteristics with per-request parameters:

```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "input": "Hello world",
        "voice": "auto",
        "num_step": 32,                 # Inference steps (1-64, higher=better quality)
        "guidance_scale": 3.0,          # CFG scale (0-10, higher=stronger conditioning)
        "denoise": True,                # Enable denoising (recommended)
        "t_shift": 0.1,                 # Noise schedule shift (0-2, affects quality/speed)
        "position_temperature": 5.0,    # Voice diversity (0=deterministic, higher=more variation)
        "class_temperature": 0.0,       # Token sampling temperature (0=greedy, higher=random)
        "duration": 3.5                 # Fixed output duration in seconds (overrides speed)
    }
)
```

**Voice Consistency & Reproducibility:**

For deterministic, reproducible output (same voice every time):
```python
{
    "position_temperature": 0.0,  # Greedy/deterministic voice selection
    "class_temperature": 0.0      # Greedy token sampling
}
```

This is especially useful for:
- Streaming with consistent voice across sentences
- Reproducible synthesis for testing
- Fixed voice character in production

Higher `position_temperature` (default 5.0) produces more voice diversity in auto mode but may cause inconsistency when streaming.

**Fixed Duration for Video Sync:**

Use `duration` to generate audio of exact length for syncing with video or animations:
```python
{
    "duration": 5.0  # Generate exactly 5 seconds of audio
}
```

When both `duration` and `speed` are provided, `duration` takes precedence and `speed` is ignored.

These parameters override server defaults on a per-request basis.

## Examples

See the `examples/` directory:

- **`python_client.py`** - Comprehensive Python client examples
- **`streaming_player.py`** - Real-time streaming audio player
- **`curl_examples.sh`** - cURL command examples

Run examples:

```bash
# Python client
cd examples
python python_client.py

# Streaming player (requires pyaudio)
pip install pyaudio
python streaming_player.py "Hello, this is streaming audio!"

# cURL examples
chmod +x curl_examples.sh
./curl_examples.sh
```

## Docker Deployment

### Quick Start with Docker Compose

```bash
# Start the server
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the server
docker-compose down
```

The server will be available at `http://localhost:8880`. Voice profiles are persisted in the `./profiles` directory.

### Build and Run Manually

```bash
# Build the image
docker build -t omnivoice-server .

# Run the container
docker run -d \
  -p 8880:8880 \
  -v $(pwd)/profiles:/app/profiles \
  -e OMNIVOICE_API_KEY=your-secret-key \
  --name omnivoice \
  omnivoice-server

# View logs
docker logs -f omnivoice
```

### Configuration

Set environment variables in `docker-compose.yml` or pass them with `-e`:

- `OMNIVOICE_HOST=0.0.0.0` - Bind host (must be 0.0.0.0 in Docker)
- `OMNIVOICE_PORT=8880` - Server port
- `OMNIVOICE_DEVICE=cpu` - Device (cpu, cuda)
- `OMNIVOICE_NUM_STEP=32` - Inference steps
- `OMNIVOICE_API_KEY=secret` - Optional authentication

For CUDA GPU support, see comments in `docker-compose.yml`.

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/maemreyo/omnivoice-server.git
cd omnivoice-server

# Install with dev dependencies
pip install -e ".[dev]"
```

### Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=omnivoice_server --cov-report=term-missing

# Run specific test
pytest tests/test_streaming.py -v
```

### Code Quality

```bash
# Lint
ruff check omnivoice_server/ tests/

# Format
ruff format omnivoice_server/ tests/

# Type check
mypy omnivoice_server/
```

### CI/CD

GitHub Actions workflow runs on every push:
- Linting (ruff)
- Type checking (mypy)
- Tests (pytest)
- Python 3.10, 3.11, 3.12

## Hardware Requirements

- **CPU**: 4+ cores recommended
- **RAM**: 8GB minimum, 16GB recommended
- **GPU**:
  - ✅ **NVIDIA GPU with CUDA** - Recommended for production (20-25x faster than CPU)
  - ❌ **Apple Silicon (MPS)** - Currently broken due to PyTorch bugs, do not use
  - ✅ **CPU** - Works but slow (5x slower than real-time)
- **Storage**: 3GB for model cache

### Device Comparison

| Device | Audio Quality | Speed (RTF) | Status |
|--------|---------------|-------------|--------|
| CPU | ✅ Excellent | 4.92 (slow) | Use for dev |
| MPS (Apple Silicon) | ❌ Broken | N/A | Do not use |
| CUDA (NVIDIA GPU) | ✅ Excellent | ~0.2 (fast) | Use for prod |

**Note**: Default device is now `cpu` due to MPS issues. See [`docs/verification/MPS_ISSUE.md`](./docs/verification/MPS_ISSUE.md) for technical details.

## Performance

**Verified benchmark results (CPU, num_step=32):**

| Metric | Value |
|--------|-------|
| Latency | 10.2 seconds per voice |
| RTF (Real-Time Factor) | 4.92 |
| Memory | Stable, no leaks |

**Expected performance on different hardware:**

| Hardware | num_step | Latency (short text) | RTF |
|----------|----------|---------------------|-----|
| CPU (Intel i7) | 32 | ~10s | 4.92 |
| GPU (RTX 3090) | 32 | ~0.5s | ~0.2 |
| Apple M1 Max (MPS) | 32 | ❌ Broken audio | N/A |

Streaming mode reduces perceived latency by sending audio as soon as the first sentence is ready.

## Troubleshooting

### Model Download Issues

The model is downloaded from HuggingFace on first run. If you encounter issues:

```bash
# Pre-download the model
python -c "from omnivoice import OmniVoice; OmniVoice.from_pretrained('k2-fsa/OmniVoice')"

# Or use a local model
omnivoice-server --model-id /path/to/local/model
```

### CUDA Out of Memory

Reduce concurrent requests or use CPU:

```bash
omnivoice-server --max-concurrent 1 --device cpu
```

### Audio Quality Issues

Increase inference steps for better quality:

```bash
omnivoice-server --num-step 32
```

## Known Limitations

### Streaming Voice Consistency

When using `stream=True` with `voice="auto"`, each sentence is synthesized independently. This can result in different voices being selected for different sentences within the same stream, as there is no shared state between sentence-level synthesis calls.

**Workarounds:**

1. **Set position_temperature=0 for deterministic voice selection (recommended):**
   ```python
   with httpx.stream(
       "POST",
       "http://127.0.0.1:8880/v1/audio/speech",
       json={
           "input": "Long text...",
           "voice": "auto",
           "stream": True,
           "position_temperature": 0.0  # Deterministic voice selection
       }
   ) as response:
       for chunk in response.iter_bytes():
           play_audio(chunk)
   ```
   This ensures the same voice is selected for each sentence, providing consistency across the stream.

2. **Use voice cloning for consistent streaming:**
   ```python
   # Create a profile first
   with open("reference.wav", "rb") as f:
       httpx.post(
           "http://127.0.0.1:8880/v1/voices/profiles",
           data={"profile_id": "consistent_voice"},
           files={"ref_audio": f}
       )
   
   # Stream with consistent voice
   with httpx.stream(
       "POST",
       "http://127.0.0.1:8880/v1/audio/speech",
       json={
           "input": "Long text...",
           "voice": "clone:consistent_voice",
           "stream": True
       }
   ) as response:
       for chunk in response.iter_bytes():
           play_audio(chunk)
   ```

3. **Use design mode with specific attributes:**
   ```python
   {
       "voice": "design:female,british accent",
       "stream": True
   }
   ```

This limitation is inherent to the sentence-by-sentence streaming architecture and does not affect non-streaming synthesis.

## Documentation

Comprehensive technical documentation is available in the `docs/` directory:

| Document | Description |
|----------|-------------|
| [verification/VERIFICATION_RESULTS.md](./docs/verification/VERIFICATION_RESULTS.md) | ⭐ Verification results and benchmark data |
| [verification/MPS_ISSUE.md](./docs/verification/MPS_ISSUE.md) | Technical analysis of Apple Silicon MPS bug |
| [system/ecosystem.md](./docs/system/ecosystem.md) | System context, hardware requirements, deployment |
| [system/specification.md](./docs/system/specification.md) | Complete system specification |
| [architecture/overview.md](./docs/architecture/overview.md) | Architecture diagrams and component maps |
| [design/dataflow.md](./docs/design/dataflow.md) | Data flow and API design details |

## License

MIT

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Run code quality checks
5. Submit a pull request

## Acknowledgments

Built on top of [OmniVoice](https://github.com/k2-fsa/OmniVoice) by k2-fsa.

## Support

- **Issues**: [GitHub Issues](https://github.com/maemreyo/omnivoice-server/issues)
- **Discussions**: [GitHub Discussions](https://github.com/maemreyo/omnivoice-server/discussions)
