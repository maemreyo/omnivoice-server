## Quick Start

### Prerequisites

**PyTorch must be installed before installing omnivoice-server.** The correct PyTorch variant depends on your hardware:

```bash
# CPU only (works everywhere, but slow)
pip install torchcodec==0.11 torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu

# NVIDIA GPU (CUDA) - recommended for production
pip install torchcodec==0.11 torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128

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

**Voice Control**: `/v1/audio/speech` accepts explicit `instructions` (strongest control), plus OpenAI-style preset names in `voice` or `speaker` (server-only convenience mappings). If none are provided, it falls back to the default design prompt: `male, middle-aged, moderate pitch, british accent`
