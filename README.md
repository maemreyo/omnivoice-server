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

`/v1/audio/speech` accepts explicit `instructions`, plus OpenAI-style preset names in
`voice` or `speaker`. If none are provided, it falls back to the default design prompt:
`male, middle-aged, moderate pitch, british accent`

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
    "input": "Hello, this is OmniVoice text-to-speech!"
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
        "instructions": "female,british accent,young adult,high pitch"
    }
)
```

`instructions` is the strongest control and overrides preset selection. If `instructions`
is absent, `/v1/audio/speech` also accepts OpenAI-style preset names in `voice` or
`speaker`, such as `alloy`, `nova`, `onyx`, and `shimmer`. Unknown values are ignored,
and the server falls back to the default design prompt `male, middle-aged, moderate pitch, british accent`.

Available attributes:
- **Gender**: male, female
- **Age**: child, teenager, young adult, middle-aged, elderly
- **Pitch**: very low pitch, low pitch, moderate pitch, high pitch, very high pitch
- **Style**: whisper
- **Accent (English)**: american accent, british accent, australian accent, chinese accent, canadian accent, indian accent, korean accent, portuguese accent, russian accent, japanese accent
- **Dialect (Chinese)**: 河南话, 陕西话, 四川话, 贵州话, 云南话, 桂林话, 济南话, 石家庄话, 甘肃话, 宁夏话, 青岛话, 东北话

OpenAI-compatible local presets:
- `alloy`, `ash`, `ballad`, `cedar`, `coral`, `echo`, `fable`, `marin`, `nova`, `onyx`, `sage`, `shimmer`, `verse`

Preset mapping table:

| Preset | Local design prompt |
|--------|---------------------|
| `alloy` | `female, young adult, moderate pitch, american accent` |
| `ash` | `male, young adult, low pitch, american accent` |
| `ballad` | `male, middle-aged, low pitch, british accent` |
| `cedar` | `male, middle-aged, low pitch, american accent` |
| `coral` | `female, young adult, high pitch, australian accent` |
| `echo` | `male, middle-aged, moderate pitch, canadian accent` |
| `fable` | `female, middle-aged, moderate pitch, british accent` |
| `marin` | `female, middle-aged, moderate pitch, canadian accent` |
| `nova` | `female, young adult, high pitch, american accent` |
| `onyx` | `male, middle-aged, very low pitch, british accent` |
| `sage` | `female, elderly, low pitch, british accent` |
| `shimmer` | `female, young adult, very high pitch, american accent` |
| `verse` | `male, young adult, moderate pitch, british accent` |

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

# Profiles are stored for management and inspection.
# For synthesis, use POST /v1/audio/speech/clone with reference audio.
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
| `--max-concurrent` | `OMNIVOICE_MAX_CONCURRENT` | `2` | Max concurrent requests |
| `--api-key` | `OMNIVOICE_API_KEY` | `""` | Bearer token (empty = no auth) |
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
  "voice": "alloy",
  "speaker": "onyx",
  "instructions": "female,british accent",
  "response_format": "wav",
  "speed": 1.0,
  "stream": false,
  "num_step": 32
}
```

Precedence:
- `instructions`
- `speaker` preset
- `voice` preset
- server default prompt

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
    {
      "id": "auto",
      "type": "auto",
      "description": "Ignored by /v1/audio/speech; server default design prompt is male, middle-aged, moderate pitch, british accent"
    },
    {"id": "design:<attributes>", "type": "design", "description": "..."},
    {"id": "alloy", "type": "preset", "description": "..."},
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

Prometheus-style metrics.

## Advanced Features

### Non-Verbal Symbols

OmniVoice natively supports non-verbal symbols inline in text. These are pass-through features from the upstream model:

```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "input": "Hello [laughter] this is amazing [breath] really cool [sigh]"
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
        "input": "这是拼音(pīn yīn)提示的例子"
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
    "position_temperature": 0.0,  # Greedy/deterministic voice rendering
    "class_temperature": 0.0      # Greedy token sampling
}
```

This is especially useful for:
- Streaming with consistent voice across sentences
- Reproducible synthesis for testing
- Fixed voice character in production

Higher `position_temperature` (default 5.0) produces more variation from the default design prompt and may cause inconsistency when streaming.

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

When using `stream=True`, each sentence is synthesized independently from the same instructions or default design prompt. With non-zero temperature settings, timbre can still drift across chunks because there is no shared state between sentence-level synthesis calls.

**Workarounds:**

1. **Set position_temperature=0 for deterministic voice rendering (recommended):**
   ```python
   with httpx.stream(
       "POST",
       "http://127.0.0.1:8880/v1/audio/speech",
       json={
           "input": "Long text...",
           "stream": True,
           "position_temperature": 0.0  # Deterministic voice rendering
       }
   ) as response:
       for chunk in response.iter_bytes():
           play_audio(chunk)
   ```
   This minimizes chunk-to-chunk variation and provides more consistent streaming output.

2. **Use one-shot voice cloning for consistent results:**
   ```python
   with open("reference.wav", "rb") as f:
       response = httpx.post(
           "http://127.0.0.1:8880/v1/audio/speech/clone",
           data={"text": "Long text..."},
           files={"ref_audio": f}
       )
   if response.status_code == 200:
       audio_bytes = response.content
   ```

3. **Use explicit instructions for a stable voice character:**
   ```python
   {
       "instructions": "female,british accent",
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
