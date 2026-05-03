# Multi-stage build for omnivoice-server
FROM python:3.10-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY omnivoice_server ./omnivoice_server

# Install PyTorch CPU (smaller image, works everywhere)
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# Install the package
RUN pip install --no-cache-dir .

# Runtime stage
FROM python:3.10-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin/omnivoice-server /usr/local/bin/omnivoice-server

# Create profile directory
RUN mkdir -p /app/profiles

# Expose server port
EXPOSE 8880

# Run server
CMD ["omnivoice-server", "--host", "0.0.0.0", "--port", "8880", "--profile-dir", "/app/profiles"]
