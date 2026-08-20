## Verification Status

**Last Updated**: 2026-04-04
**Status**: Working (CPU only)

### Quick Summary

- System works - Produces clear, high-quality audio for English and Vietnamese
- MPS broken - Apple Silicon GPU has PyTorch bugs, use CPU instead
- CPU slow - RTF=4.92 (5x slower than real-time, ~10s per voice)
- No memory leaks - Stable memory usage verified
- Browser CORS support verified for local cross-origin frontends

### Benchmark Results (CPU)

| Metric | Value | Status |
|--------|-------|--------|
| Latency (mean) | 10.2 seconds | Slow |
| RTF (Real-Time Factor) | 4.92 | 5x slower than real-time |
| Memory leak | None | Stable |
| Audio quality | Excellent | Clear speech |

### Production Recommendation

**For production, deploy on NVIDIA GPU (CUDA):**
- 20-25x faster than CPU (RTF~0.2)
- Cloud options: AWS g5.xlarge (~$1/hr), GCP T4/V100, RunPod (~$0.40/hr)

**Detailed reports**: See [`docs/verification/`](./docs/verification/) for full verification results and technical details.

### Browser Integration Status

- Cross-origin browser access is supported via configurable CORS
- Verified preflight success for browser clients on a separate local origin
- Verified unauthorized browser requests return `401` with CORS headers intact
- Verified authorized browser requests return `200` and expose audio metadata headers

For setup and smoke-test commands, see:

- [`Configuration`](./06-configuration.md)
- [`Troubleshooting`](./14-troubleshooting.md)

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
