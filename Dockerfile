# Multi-stage build for omnivoice-server
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY omnivoice_server ./omnivoice_server

# Install PyTorch CPU (smaller image, works everywhere).
# Versions are pinned to match ci.yml. Unpinned, pip resolved a newer torch
# whose dependencies needed an sdist build, and --index-url REPLACES PyPI, so
# the build backend (flit_core) was unresolvable and the image failed to build.
# Deliberately no --extra-index-url here: PyPI also publishes torch==2.8.0 as
# the CUDA-bundled build, and pip may pick either for an equal version.
RUN pip install --no-cache-dir torch==2.8.0 torchaudio==2.8.0 \
    --index-url https://download.pytorch.org/whl/cpu

# Install the package
RUN pip install --no-cache-dir .

# Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/omnivoice-server /usr/local/bin/omnivoice-server

# Create profile directory
RUN mkdir -p /app/profiles

# Expose server port
EXPOSE 8880

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8880/health')" || exit 1

# Run server
CMD ["omnivoice-server", "--host", "0.0.0.0", "--port", "8880", "--profile-dir", "/app/profiles"]
