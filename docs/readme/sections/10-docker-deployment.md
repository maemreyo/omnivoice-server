## Docker Deployment

The default Docker image is CUDA-enabled and targets NVIDIA GPUs. It contains
PyTorch 2.8/cu128, the matching TorchCodec 0.7 release, FFmpeg, and the pinned
FlashInfer runtime. The host needs an NVIDIA driver compatible with CUDA 12.8,
the NVIDIA Container Toolkit, and Docker Compose v2.

### CUDA quick start

```bash
# Pull the published CUDA image and start it with GPU access.
docker compose pull
docker compose up -d

docker compose logs -f
curl http://localhost:8880/health
```

To build from the current checkout instead:

```bash
docker compose build
docker compose up -d
```

The default image is `ghcr.io/remominor/omnivoice-server:latest`. `latest` is
always the CUDA image; `cuda-latest` is also published as an explicit alias.
Voice profiles and downloaded Hugging Face model files use named Docker volumes
so the non-root container process can write them safely.

Run the CUDA image manually with:

```bash
docker run --rm --gpus all \
  -p 8880:8880 \
  -v omnivoice-profiles:/data/profiles \
  -v omnivoice-hf-cache:/cache/huggingface \
  ghcr.io/remominor/omnivoice-server:latest
```

### RTX 3070 profiles

The Compose defaults use the regular CUDA inference path with TF32 and one
concurrent synthesis request. FlashInfer is installed but remains opt-in until
it has been benchmarked on the target card.

For the speed-oriented profile:

```bash
OMNIVOICE_FLASHINFER_MODE=true \
OMNIVOICE_FLASHINFER_CUDA_GRAPH=true \
docker compose up -d
```

For the lower steady-state VRAM profile on an 8 GB RTX 3070:

```bash
OMNIVOICE_LOW_VRAM_MODE=true \
OMNIVOICE_SPLIT_CFG_BATCH=true \
docker compose up -d
```

Do not enable FlashInfer CUDA graphs and low-VRAM mode together without
measuring the workload. The detailed tradeoffs and benchmark commands are in
[`VRAM_OPTIMIZATION.md`](../../../VRAM_OPTIMIZATION.md).

### CPU image

CPU deployment is intentionally separate from the CUDA default:

```bash
docker compose -f docker-compose-cpu.yml build
docker compose -f docker-compose-cpu.yml up -d
```

The CPU image is built locally from `Dockerfile.cpu`. The GitHub Actions
workflow does not build or publish CPU images.

### Configuration

Compose accepts the normal `OMNIVOICE_*` settings. Common overrides include:

- `OMNIVOICE_HOST_PORT=8880` — host port mapped to container port 8880.
- `OMNIVOICE_API_KEY=secret` — optional bearer-token authentication.
- `HF_TOKEN=...` — optional Hugging Face token for gated model downloads.
- `OMNIVOICE_MAX_CONCURRENT=1` — simultaneous synthesis requests.
- `OMNIVOICE_LOW_VRAM_MODE=true` — lazy reference encoder loading.
- `OMNIVOICE_SPLIT_CFG_BATCH=true` — lower peak CFG tensor memory.
- `OMNIVOICE_FLASHINFER_MODE=true` — enable FlashInfer acceleration.
- `OMNIVOICE_FLASHINFER_CUDA_GRAPH_MAX_SHAPES=4` — cap retained CUDA-graph
  shapes to prevent text-length diversity from growing private VRAM pools.
  Reference-conditioned clone requests bypass graph capture automatically.
- `OMNIVOICE_FLASHINFER_CUDA_GRAPH=true` — enable its CUDA graph path.

Use `OMNIVOICE_IMAGE` to override the CUDA image name or
`OMNIVOICE_CPU_IMAGE` for the CPU Compose file.

### GitHub container publishing

`.github/workflows/docker-publish.yml` validates the CUDA image on pull
requests. On pushes to `main`, version tags, and manual dispatches, it publishes
the CUDA image to this repository's GHCR namespace using `GITHUB_TOKEN`:

- `latest`, `cuda-latest`, version, and SHA tags point to the CUDA image.

No Docker Hub credentials are required.
