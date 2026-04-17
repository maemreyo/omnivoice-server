# omnivoice-server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/maemreyo/omnivoice-server/actions/workflows/ci.yml/badge.svg)](https://github.com/maemreyo/omnivoice-server/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/omnivoice-server.svg)](https://pypi.org/project/omnivoice-server/)

OpenAI-compatible HTTP server for [OmniVoice](https://github.com/k2-fsa/OmniVoice) text-to-speech.

**Author:** zamery ([@maemreyo](https://github.com/maemreyo)) | **Email:** matthew.ngo1114@gmail.com

> **Early Development Notice**
>
> This is a new repository built on top of OmniVoice (released 2026). Both the upstream model and this server wrapper are under active development. Expect API changes, breaking updates, and performance improvements as PyTorch MPS support matures.
>
> **Current Status**: Functional on CPU and CUDA. MPS (Apple Silicon) has known issues.

## Quick Links

| Category | Sections |
|----------|----------|
| **Getting Started** | [Features](docs/readme/sections/01-features.md) - [Quick Start](docs/readme/sections/02-quick-start.md) - [Verification Status](docs/readme/sections/03-verification-status.md) |
| **Usage** | [API Usage](docs/readme/sections/04-api-usage.md) - [CLI Usage](docs/readme/sections/05-cli-usage.md) - [Configuration](docs/readme/sections/06-configuration.md) |
| **Reference** | [API Reference](docs/readme/sections/07-api-reference.md) - [Advanced Features](docs/readme/sections/08-advanced-features.md) - [Examples](docs/readme/sections/09-examples.md) |
| **Deployment** | [Docker Deployment](docs/readme/sections/10-docker-deployment.md) - [Hardware Requirements](docs/readme/sections/12-hardware-requirements.md) - [Performance](docs/readme/sections/13-performance.md) |
| **Development** | [Development](docs/readme/sections/11-development.md) - [Troubleshooting](docs/readme/sections/14-troubleshooting.md) - [Known Limitations](docs/readme/sections/15-known-limitations.md) |
| **Project** | [Documentation Index](docs/readme/sections/16-documentation-index.md) - [License](docs/readme/sections/17-license.md) - [Contributing](docs/readme/sections/18-contributing.md) - [Acknowledgments](docs/readme/sections/19-acknowledgments.md) - [Support](docs/readme/sections/20-support.md) |

## Quick Start

**Prerequisites**: PyTorch must be installed first. See [Quick Start](docs/readme/sections/02-quick-start.md) for details.

```bash
# Install
pip install omnivoice-server

# Start server
omnivoice-server

# Test with curl
curl -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model": "omnivoice", "input": "Hello world!"}' \
  --output speech.wav
```

## Overview

**omnivoice-server** wraps the OmniVoice TTS model with an OpenAI-compatible HTTP API:

- **Voice Design**: Control gender, age, pitch, accent, dialect
- **Voice Cloning**: Clone from reference audio
- **Streaming**: Real-time audio streaming with chunked transfer
- **Voice Profiles**: Persistent storage for cloned voices
- **OpenAI-Compatible**: Drop-in replacement for OpenAI TTS endpoints

See [Features](docs/readme/sections/01-features.md) for complete capability list.

## Verification Status

- **System**: Working on CPU and CUDA
- **MPS**: Broken on Apple Silicon (use CPU instead)
- **Performance**: RTF ~4.92 on CPU, ~0.2 on GPU

See [Verification Status](docs/readme/sections/03-verification-status.md) for benchmarks and audio samples.

## Documentation

This README provides quick links to detailed documentation. For complete information, see:

- Individual section files in `docs/readme/sections/`
- Technical docs in `docs/verification/`, `docs/system/`, `docs/architecture/`

## License

MIT - See [License](docs/readme/sections/17-license.md)

## Support

- [GitHub Issues](https://github.com/maemreyo/omnivoice-server/issues)
- [GitHub Discussions](https://github.com/maemreyo/omnivoice-server/discussions)
