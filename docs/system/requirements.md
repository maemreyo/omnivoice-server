# System Requirements

## Minimum Requirements

| Component | Minimum |
|-----------|---------|
| RAM | 8 GB (model uses ~1.7 GB; OS and app need headroom) |
| Disk | 5 GB free (model ~3 GB + Python runtime) |
| CPU | x86_64 or ARM64 |
| Python | 3.10+ |

## Recommended

| Component | Recommended |
|-----------|-------------|
| RAM | 16 GB |
| Disk | 10 GB free |
| CPU | 4+ cores (inference is single-threaded but OS overhead benefits from cores) |

## Notes

- **GPU**: Not required. CPU inference works but is slower (~3-10× vs GPU).
- **MPS (Apple Silicon)**: Currently disabled due to an upstream OmniVoice bug. Server defaults to CPU on macOS.
- **Model download**: First run downloads ~3 GB from HuggingFace. Set `OMNIVOICE_MODEL_CACHE_DIR` to control where it's stored.
- **Memory pressure**: On systems with <8 GB RAM, the OS may OOM-kill the server process. Watch the `/health` endpoint's `memory_rss_mb` field.
