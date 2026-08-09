# omnivoice-server (fork)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/NguyenNinh05/omnivoice-server/actions/workflows/ci.yml/badge.svg)](https://github.com/NguyenNinh05/omnivoice-server/actions/workflows/ci.yml)

OpenAI-compatible HTTP server for [OmniVoice](https://github.com/k2-fsa/OmniVoice) text-to-speech.

> **This is a fork.**
> Upstream: [maemreyo/omnivoice-server](https://github.com/maemreyo/omnivoice-server) by zamery ([@maemreyo](https://github.com/maemreyo)), MIT licensed.
> This fork is maintained by [@NguyenNinh05](https://github.com/NguyenNinh05) and tracks the newer `omnivoice` 0.2.x line.

## ⚠️ Installation: do not use `pip install omnivoice-server`

The name `omnivoice-server` on PyPI belongs to **upstream**. Installing it gives you
upstream's build, not this fork. This fork is **not published to PyPI** — install it
from Git.

**Prerequisites:** PyTorch must be installed first — the correct variant depends on
your hardware. See [Quick Start](docs/readme/sections/02-quick-start.md).

```bash
# CPU
pip install torchcodec==0.11 torch==2.8.0 torchaudio==2.8.0 \
  --index-url https://download.pytorch.org/whl/cpu

# Then install this fork
pip install git+https://github.com/NguyenNinh05/omnivoice-server.git
```

Or clone for development:

```bash
git clone https://github.com/NguyenNinh05/omnivoice-server.git
cd omnivoice-server
pip install -e ".[dev]"
```

Both install the console script `omnivoice-server`, same as upstream. If you
previously installed the PyPI package, uninstall it first (`pip uninstall
omnivoice-server`) so the two don't shadow each other.

## Quick Start

```bash
# Start server
omnivoice-server

# Test with curl
curl -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model": "omnivoice", "input": "Hello world!"}' \
  --output speech.wav
```

## What this fork changes

Upstream pins `omnivoice>=0.1.0,<0.2.0`, which locks it out of the entire 0.2.x
line. This fork requires **`omnivoice>=0.2.1,<0.3.0`** and exposes the parameters
those releases added:

| Change | Why it matters |
|---|---|
| `pad_duration`, `fade_duration` (upstream 0.2.0) | Mitigates clipped word endings — see below |
| `normalize_text` (upstream 0.2.1) | Expands numbers/dates/currency. Off by default; needs the `omnivoice[tn]` extra |
| `asr_model_name`, `asr_device` (upstream 0.2.1) | Keeps Whisper off the TTS GPU. Upstream previously pinned ASR to GPU 0 |
| Picks up upstream's 0.2.0 punctuation fix | Closes the dropped-phoneme-before-`,`/`.` bug ([k2-fsa/OmniVoice#116](https://github.com/k2-fsa/OmniVoice/issues/116)) |

### Clipped word endings

OmniVoice still clips the tail of generated audio in some languages
([k2-fsa/OmniVoice#245](https://github.com/k2-fsa/OmniVoice/issues/245), open as of
omnivoice 0.2.1). Raise `pad_duration` so the clip lands in padding instead of on a
real phoneme:

```bash
omnivoice-server --pad-duration 0.3
```

Per request: `{"input": "...", "pad_duration": 0.3}`. If endings still get swallowed,
push `guidance_scale` toward `2.5`–`3.5`.

Note that the older community workaround — inserting a space before commas and
periods — is obsolete on 0.2.x and now just injects wrong prosody.

## Overview

Wraps the OmniVoice TTS model with an OpenAI-compatible HTTP API:

- **Voice Design**: control gender, age, pitch, accent, dialect
- **Voice Cloning**: clone from reference audio, with persistent profiles
- **Multi-speaker scripts**: `/v1/audio/script`, single- or multi-track output
- **Streaming**: sentence-level chunked PCM
- **OpenAI-compatible**: drop-in for OpenAI TTS endpoints

See [Features](docs/readme/sections/01-features.md) for the complete list.

## Documentation

| Category | Sections |
|----------|----------|
| **Getting Started** | [Features](docs/readme/sections/01-features.md) - [Quick Start](docs/readme/sections/02-quick-start.md) - [Verification Status](docs/readme/sections/03-verification-status.md) |
| **Usage** | [API Usage](docs/readme/sections/04-api-usage.md) - [CLI Usage](docs/readme/sections/05-cli-usage.md) - [Configuration](docs/configuration.md) |
| **Reference** | [API Reference](docs/readme/sections/07-api-reference.md) - [Advanced Features](docs/readme/sections/08-advanced-features.md) - [Examples](docs/readme/sections/09-examples.md) |
| **Deployment** | [Docker](docs/readme/sections/10-docker-deployment.md) - [Hardware](docs/readme/sections/12-hardware-requirements.md) - [Performance](docs/readme/sections/13-performance.md) - [Benchmarks](BENCHMARKS.md) |
| **Development** | [Development](docs/readme/sections/11-development.md) - [Architecture](docs/architecture/overview.md) - [Troubleshooting](docs/readme/sections/14-troubleshooting.md) - [Known Limitations](docs/readme/sections/15-known-limitations.md) |

## Platform status

- **CPU and CUDA**: working
- **MPS (Apple Silicon)**: broken — use `--device cpu`. See [MPS_ISSUE.md](docs/verification/MPS_ISSUE.md)
- Non-WAV/PCM formats (mp3, opus, aac, flac) need the `formats` extra **and** system `ffmpeg`

> Performance figures and audio samples in the docs were measured by upstream on
> `omnivoice` 0.1.x and have **not** been re-measured on 0.2.x. Treat them as
> indicative until re-run — see [BENCHMARKS.md](BENCHMARKS.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Changes that are not fork-specific are
better sent to [upstream](https://github.com/maemreyo/omnivoice-server) so everyone
benefits.

## License

MIT — see [LICENSE](LICENSE).

Original work Copyright (c) 2026 zamery (maemreyo). This fork retains that
copyright notice as required by the MIT license; modifications are made under the
same terms.

## Support

Issues **with this fork**: [GitHub Issues](https://github.com/NguyenNinh05/omnivoice-server/issues)

For bugs in the underlying model, report to
[k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice/issues) instead.
