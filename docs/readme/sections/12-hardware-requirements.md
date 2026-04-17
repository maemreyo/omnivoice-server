## Hardware Requirements

- **CPU**: 4+ cores recommended
- **RAM**: 8GB minimum, 16GB recommended
- **GPU**:
  - NVIDIA GPU with CUDA - Recommended for production (20-25x faster than CPU)
  - Apple Silicon (MPS) - Currently broken due to PyTorch bugs, do not use
  - CPU - Works but slow (5x slower than real-time)
- **Storage**: 3GB for model cache

### Device Comparison

| Device | Audio Quality | Speed (RTF) | Status |
|--------|---------------|-------------|--------|
| CPU | Excellent | 4.92 (slow) | Use for dev |
| MPS (Apple Silicon) | Broken | N/A | Do not use |
| CUDA (NVIDIA GPU) | Excellent | ~0.2 (fast) | Use for prod |

**Note**: Default device is now `cpu` due to MPS issues. See [`docs/verification/MPS_ISSUE.md`](./docs/verification/MPS_ISSUE.md) for technical details.
