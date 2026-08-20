## Performance

**Verified benchmark results (CPU, num_step=32):**

| Metric | Value |
|--------|-------|
| Latency | 10.2 seconds per voice |
| RTF (Real-Time Factor) | 4.92 |
| Memory | Stable, no leaks |

**Expected performance on different hardware:**

| Hardware | num_step | Latency (short text) | RTF |
|----------|----------|---------------------|-----|
| CPU (Intel i7) | 32 | ~10s | 4.92 |
| GPU (RTX 3090) | 32 | ~0.5s | ~0.2 |
| Apple M1 Max (MPS) | 32 | Broken audio | N/A |

Streaming mode reduces perceived latency by sending audio as soon as the first sentence is ready.
