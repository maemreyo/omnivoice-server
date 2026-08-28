# Performance Benchmarks

This document contains performance benchmarks for omnivoice-server across different hardware configurations.

## Credits

These benchmark results were contributed by [@entermask](https://github.com/entermask). Thank you for running the benchmarks and sharing the results!

## NVIDIA A100 / H100 (CUDA)

**Device:** CUDA  
**Date:** May 16, 2026  
**Contributor:** [@entermask](https://github.com/entermask)

### Performance Metrics

| Device | Steps | Test Case | Mean (ms) | p95 (ms) | Mean RTF | Errors |
|--------|-------|-----------|-----------|----------|----------|--------|
| cuda | 32 | long_auto | 1779 | 2018 | 0.0845 | 0 |
| cuda | 32 | medium_auto | 1756 | 1938 | 0.1635 | 0 |
| cuda | 32 | medium_clone | 8930 | 9357 | 0.0864 | 0 |
| cuda | 32 | short_auto | 1669 | 1851 | 0.8032 | 0 |
| cuda | 32 | short_design | 1745 | 1986 | 0.9957 | 0 |

### Memory Usage (RAM across all runs)

| Test Case | Initial RAM (MB) | Final RAM (MB) | Total Δ (MB) | Leak? |
|-----------|-----------------|----------------|--------------|-------|
| long_auto | 2797 | 2803 | +6 | ✅ NO |
| medium_auto | 2781 | 2791 | +10 | ✅ NO |
| medium_clone | 3259 | 3271 | +12 | ✅ NO |
| short_auto | 2730 | 2767 | +37 | ✅ NO |
| short_design | 2803 | 2803 | +0 | ✅ NO |

### Interpretation

- **RTF < 1.0**: Faster than real-time (good)
- **RTF > 1.0**: Slower than real-time (server usable but audio chunks will lag)
- **RAM Δ > 200MB** across 100 runs = memory leak detected

### Summary

All test cases run significantly faster than real-time (RTF < 1.0), with the fastest being `long_auto` at 0.0845 RTF. No memory leaks were detected across any test case, indicating stable memory usage over extended runs.

---

## Contributing Benchmarks

If you'd like to contribute benchmark results for your hardware configuration, please:

1. Run the benchmark tests following the documentation
2. Create a new section in this document with your results
3. Include your GitHub username for attribution
4. Open a pull request or create an issue with your results
