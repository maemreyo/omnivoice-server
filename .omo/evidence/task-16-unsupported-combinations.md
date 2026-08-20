# Task 16: Unsupported Combinations Documentation

**Date**: 2026-04-19
**Task**: Document unsupported combinations explicitly
**Status**: COMPLETE

## Explicitly Unsupported Combinations

These combinations are **KNOWN** to be unsupported and should NOT be attempted:

### 1. faster-whisper + MPS Device

**Configuration**: `faster-whisper` backend on macOS with MPS device

**Status**: ❌ UNSUPPORTED

**Reason**: The `faster-whisper` library does not support Apple's Metal Performance Shaders (MPS) backend. This is an upstream limitation.

**Evidence**: 
- Task 3 compatibility matrix line 32
- `.sisyphus/notepads/torchcodec-windows-long-term-fix/compatibility-matrix.md`

**Workaround**: Use CPU device on macOS when using faster-whisper backend:
```bash
export OMNIVOICE_ASR_BACKEND=faster-whisper
omnivoice-infer --device cpu ...
```

**Documentation Status**: ✅ Documented in compatibility matrix

---

### 2. Python < 3.10

**Configuration**: Any backend on Python versions below 3.10

**Status**: ❌ UNSUPPORTED

**Reason**: Project minimum requirement is Python 3.10+

**Evidence**: 
- Task 3 compatibility matrix line 52
- Project documentation

**Impact**: 
- OmniVoice may fail to import
- Dependencies may be incompatible
- Type hints and language features require 3.10+

**Workaround**: Upgrade to Python 3.10 or higher

**Documentation Status**: ✅ Documented in compatibility matrix

**Note**: The local validation environment (Python 3.9.6) falls into this unsupported category, which is why runtime validation could not be completed.

---

### 3. transformers + Windows + Misaligned torch/torchaudio/torchcodec

**Configuration**: `transformers` backend on Windows with mismatched PyTorch ecosystem versions

**Status**: ❌ UNSUPPORTED (short-term mitigation applied)

**Reason**: Version misalignment between torch, torchaudio, and torchcodec causes import crashes on Windows

**Evidence**: 
- Task 3 compatibility matrix line 53
- Original bug report that triggered this plan

**Short-Term Mitigation**: torchcodec is excluded from Windows installations

**Long-Term Fix**: Migrate to `faster-whisper` backend which does not depend on torchcodec

**Workaround**: 
- Use the short-term fix (torchcodec excluded on Windows)
- OR migrate to faster-whisper backend when available

**Documentation Status**: ✅ Documented in compatibility matrix and troubleshooting docs

---

## Unverified Combinations (Lack Evidence)

These combinations are **NOT explicitly blocked** but lack validation evidence and should be treated as **EXPERIMENTAL** until validated:

### 4. transformers + Windows + CUDA

**Configuration**: `transformers` backend on Windows with CUDA device

**Status**: ⚠️ UNVERIFIED

**Reason**: Dependency alignment between torch, torchaudio, CUDA toolkit unclear

**Evidence**: Task 3 compatibility matrix line 59

**Risk Level**: MEDIUM - May work but needs validation

**Recommendation**: Test in staging environment before production use

**Documentation Status**: ✅ Documented as unverified in compatibility matrix

---

### 5. transformers + macOS + MPS

**Configuration**: `transformers` backend on macOS with MPS device

**Status**: ⚠️ UNVERIFIED

**Reason**: Upstream OmniVoice has documented MPS instability issues

**Evidence**: 
- Task 3 compatibility matrix line 60
- Upstream OmniVoice documentation

**Risk Level**: HIGH - Known upstream issues

**Recommendation**: Use CPU device on macOS until MPS issues resolved upstream

**Workaround**:
```bash
omnivoice-infer --device cpu ...
```

**Documentation Status**: ✅ Documented as unverified in compatibility matrix

---

### 6. faster-whisper on Any Platform

**Configuration**: `faster-whisper` backend on any platform/device combination

**Status**: ⚠️ UNVERIFIED (pending Wave 2-4 validation)

**Reason**: New backend, validation pending in later tasks

**Evidence**: Task 3 compatibility matrix line 61

**Risk Level**: MEDIUM - Implementation complete but needs validation

**Expected Support** (pending validation):
- ✅ Linux + CPU
- ✅ Linux + CUDA
- ✅ macOS + CPU
- ❌ macOS + MPS (explicitly unsupported)
- ✅ Windows + CPU
- ✅ Windows + CUDA

**Recommendation**: Wait for Task 17 transcript equivalence validation before production use

**Documentation Status**: ✅ Documented as pending validation in compatibility matrix

---

## Summary Table

| Configuration | Status | Risk | Documented |
|---------------|--------|------|------------|
| faster-whisper + MPS | ❌ UNSUPPORTED | N/A | ✅ Yes |
| Python < 3.10 | ❌ UNSUPPORTED | N/A | ✅ Yes |
| transformers + Windows + misaligned deps | ❌ UNSUPPORTED | N/A | ✅ Yes |
| transformers + Windows + CUDA | ⚠️ UNVERIFIED | MEDIUM | ✅ Yes |
| transformers + macOS + MPS | ⚠️ UNVERIFIED | HIGH | ✅ Yes |
| faster-whisper (all platforms) | ⚠️ UNVERIFIED | MEDIUM | ✅ Yes |

---

## Policy for Unverified Combinations

Per Task 3 compatibility matrix:

> **Policy:** Unverified combinations should be documented as "experimental" until validation evidence exists.

**Operator Guidance**:
1. Unverified combinations MAY work but are not guaranteed
2. Use at your own risk in production
3. Report issues with full environment details
4. Expect potential breaking changes as validation progresses

**Support Stance**:
- Issues on unverified combinations: BEST EFFORT
- Issues on unsupported combinations: WONTFIX (use workaround)
- Issues on verified combinations: SUPPORTED

---

## Validation Status

**Unsupported Combinations**: 3 documented ✅

**Unverified Combinations**: 3 documented ✅

**Ambiguous Combinations**: 0 ✅

**Documentation Coverage**: 100% ✅

---

## References

- `.sisyphus/notepads/torchcodec-windows-long-term-fix/compatibility-matrix.md` - Full compatibility matrix
- `.sisyphus/task-3-summary.md` - Task 3 completion summary
- `.sisyphus/evidence/task-15-command-matrix.txt` - Validation commands for supported paths
- `.sisyphus/evidence/task-16-validation-matrix.md` - Validation results

---

## Acceptance Criteria

From Task 16 plan:

- [x] **Every failed/unverified combination is documented as unsupported or pending** - ✅ MET
- [x] **No ambiguous grey area in support messaging** - ✅ MET
- [x] **Environment status left explicit** - ✅ MET

**Note**: This document satisfies the unsupported/unverified documentation requirement, but Task 16 overall is NOT COMPLETE because runtime validation evidence is missing (see task-16-validation-matrix.md for full status).
