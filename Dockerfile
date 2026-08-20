# syntax=docker/dockerfile:1.7

ARG PYTORCH_IMAGE=pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime
FROM ${PYTORCH_IMAGE}

ARG CUDA_WHEEL=cu128
ARG TORCHCODEC_VERSION=0.7.0
ARG FLASHINFER_VERSION=0.6.15.post1
ARG NVIDIA_NPP_VERSION=12.3.3.100
ARG APP_UID=10001
ARG APP_GID=10001

LABEL org.opencontainers.image.source="https://github.com/remominor/omnivoice-server" \
      org.opencontainers.image.description="CUDA-first OpenAI-compatible OmniVoice TTS server" \
      org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/cache/huggingface \
    TORCH_HOME=/cache/torch \
    TORCHINDUCTOR_CACHE_DIR=/cache/torchinductor \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    LD_LIBRARY_PATH=/opt/conda/lib/python3.11/site-packages/nvidia/npp/lib:/usr/local/nvidia/lib:/usr/local/nvidia/lib64 \
    OMNIVOICE_HOST=0.0.0.0 \
    OMNIVOICE_PORT=8880 \
    OMNIVOICE_DEVICE=cuda \
    OMNIVOICE_MAX_CONCURRENT=1 \
    OMNIVOICE_CUDA_TF32=true

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY omnivoice_server ./omnivoice_server

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir \
        "nvidia-npp-cu12==${NVIDIA_NPP_VERSION}" \
    && python -m pip install --no-cache-dir \
        --index-url "https://download.pytorch.org/whl/${CUDA_WHEEL}" \
        "torchcodec==${TORCHCODEC_VERSION}" \
    && python -m pip install --no-cache-dir \
        --extra-index-url "https://flashinfer.ai/whl/${CUDA_WHEEL}/" \
        ".[formats,flashinfer]" \
    && python -m pip install --no-cache-dir \
        --extra-index-url "https://flashinfer.ai/whl/${CUDA_WHEEL}/" \
        "flashinfer-jit-cache==${FLASHINFER_VERSION}+${CUDA_WHEEL}" \
    && python -m pip check

ARG TORCH_C_DLPACK_EXT_VERSION=0.1.5
RUN python -m pip install --no-cache-dir \
        "torch-c-dlpack-ext==${TORCH_C_DLPACK_EXT_VERSION}" \
    && python -m pip check

RUN groupadd --gid "${APP_GID}" omnivoice \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home omnivoice \
    && mkdir -p \
        /app \
        /data/profiles \
        /cache/huggingface \
        /cache/torch \
        /cache/torchinductor \
    && chown -R omnivoice:omnivoice /app /data /cache \
    && rm -rf /build

WORKDIR /app
USER omnivoice

VOLUME ["/data/profiles", "/cache/huggingface"]
EXPOSE 8880

HEALTHCHECK --interval=30s --timeout=10s --start-period=5m --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8880/health', timeout=5)" || exit 1

CMD ["omnivoice-server", "--profile-dir", "/data/profiles"]
