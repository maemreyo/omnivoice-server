# ASR Backend Compatibility Matrix and Rollback Policy

## Supported Environments

### transformers Backend (Current Default)

| OS | Python | Device | Status | Notes |
|---|---|---|---|---|
| Linux | 3.10+ | CPU | ✅ Supported | Current production path |
| Linux | 3.10+ | CUDA | ✅ Supported | Current production path |
| macOS | 3.10+ | CPU | ✅ Supported | Current production path |
| macOS | 3.10+ | MPS | ⚠️ Unverified | MPS issues documented upstream |
| Windows | 3.10+ | CPU | ✅ Supported | Short-term fix applied (no torchcodec) |
| Windows | 3.10+ | CUDA | ⚠️ Unverified | Dependency alignment required |

**Dependencies:**
- `transformers>=4.0.0` (already in omnivoice deps)
- `torch`, `torchaudio` (user-installed prerequisite)
- No additional install required

**Known Issues:**
- Windows: torchcodec import conflict when torch/torchaudio versions misaligned
- MPS: upstream OmniVoice has documented MPS instability

### faster-whisper Backend (Opt-In, Long-Term Target)

| OS | Python | Device | Status | Notes |
|---|---|---|---|---|
| Linux | 3.10+ | CPU | 🔄 Pending Validation | Target for Windows long-term fix |
| Linux | 3.10+ | CUDA | 🔄 Pending Validation | Primary performance target |
| macOS | 3.10+ | CPU | 🔄 Pending Validation | |
| macOS | 3.10+ | MPS | ❌ Unsupported | faster-whisper does not support MPS |
| Windows | 3.10+ | CPU | 🔄 Pending Validation | Primary Windows fix target |
| Windows | 3.10+ | CUDA | 🔄 Pending Validation | Requires CUDA toolkit + cuDNN |

**Dependencies:**
- `faster-whisper>=1.0.0` (opt-in extra or manual install)
- `torch`, `torchaudio` (user-installed prerequisite)
- CUDA path: requires CUDA toolkit + cuDNN installed separately
- **No torchcodec dependency** (key Windows fix)

**Known Limitations:**
- MPS not supported by faster-whisper upstream
- CUDA path requires system-level CUDA/cuDNN (not pip-installable)
- Model naming differs from transformers (e.g., "base" vs "openai/whisper-base")

## Unsupported Combinations

| Configuration | Reason |
|---|---|
| faster-whisper + MPS | Upstream library does not support MPS device |
| Python < 3.10 | Project minimum is 3.10 |
| transformers + Windows + misaligned torch/torchaudio/torchcodec | Causes import crash (short-term fix: exclude torchcodec on Windows) |

## Unverified Combinations

These combinations are not explicitly blocked but lack validation evidence:

- transformers + Windows + CUDA (dependency alignment unclear)
- transformers + macOS + MPS (upstream OmniVoice MPS issues)
- faster-whisper on any platform (pending Wave 2-4 validation)

**Policy:** Unverified combinations should be documented as "experimental" until validation evidence exists.

---

## Backend Selection Policy

### Initial Rollout (Wave 4, Task 18)

- **Default backend:** `transformers`
- **Opt-in backend:** `faster-whisper`
- **Rationale:** Preserve current production behavior; allow gradual migration

### Selection Mechanism (Task 4)

Backend selection will be controlled via:

1. **Environment variable:** `OMNIVOICE_ASR_BACKEND=transformers|faster-whisper`
2. **Config file:** (if server config exists) `asr_backend: transformers|faster-whisper`
3. **CLI flag:** `--asr-backend transformers|faster-whisper`

**Precedence:** CLI flag > Environment variable > Config file > Default (`transformers`)

**Validation:** Invalid backend name raises clear error at initialization time.

---

## Fallback Rules

### Backend Load Failure

| Scenario | Behavior |
|---|---|
| Selected backend import fails | Raise clear error with backend name and probable cause |
| Selected backend model load fails | Raise clear error with model name and device info |
| No fallback to alternate backend | Explicit operator selection is respected; no silent switching |

**Rationale:** Silent fallback undermines operator intent and makes debugging harder.

### Transcription Failure

| Scenario | Behavior |
|---|---|
| Transcription returns empty string | Log warning, raise error if clone mode requires transcript |
| Transcription raises exception | Propagate exception with backend context |
| Audio file unreadable | Raise clear error before backend invocation |

**Logging:** All backend load, transcription start, and failure events are logged with backend name.

---

## Rollback Policy

### Rollback Trigger Criteria (Measurable)

Rollback from `faster-whisper` to `transformers` is recommended if:

1. **Import failure rate > 5%** in production logs over 24h window
2. **Transcription failure rate > 10%** for previously working audio fixtures
3. **Clone mode success rate < 90%** compared to baseline with same fixtures
4. **Operator decision** based on environment-specific issues

### Rollback Procedure

**Step 1:** Change backend selector to `transformers`

```bash
# Environment variable
export OMNIVOICE_ASR_BACKEND=transformers

# Or CLI flag
omnivoice-server --asr-backend transformers

# Or config file (if applicable)
# Edit config.yaml: asr_backend: transformers
```

**Step 2:** Restart service/process

**Step 3:** Verify rollback success

```bash
# Check logs for backend selection confirmation
# Run clone mode test with ref_text=None
# Verify transcript generation succeeds
```

**Expected Result:** Service returns to pre-migration behavior with no code changes required.

**Evidence Location:** `.sisyphus/evidence/rollback-verification.txt`

### Rollback Safety Guarantees

- No code edits required
- No database migration required
- No model re-download required (both backends use separate model caches)
- Rollback can be executed in < 5 minutes

---

## Coexistence Strategy

### Dependency Packaging (Task 8)

Both backends can coexist in the same environment:

```toml
# pyproject.toml
[project.optional-dependencies]
asr-faster-whisper = ["faster-whisper>=1.0.0"]
```

**Install paths:**

```bash
# Default (transformers only, already included)
pip install omnivoice-server

# Opt-in faster-whisper
pip install omnivoice-server[asr-faster-whisper]

# Or manual
pip install omnivoice-server
pip install faster-whisper
```

**Conflict risk:** None. Both backends use separate model namespaces and do not share state.

### Model Storage

- **transformers:** `~/.cache/huggingface/hub/models--openai--whisper-*`
- **faster-whisper:** `~/.cache/huggingface/hub/models--Systran--faster-whisper-*`

No storage conflict. Both can be installed simultaneously.

---

## Future Default Switch Criteria (Task 19)

Switching the default from `transformers` to `faster-whisper` requires:

1. ✅ All supported environments validated (Task 16)
2. ✅ Transcript equivalence verified on fixtures (Task 17)
3. ✅ Clone mode success rate ≥ 95% across fixture set
4. ✅ Rollback procedure validated (Task 13)
5. ✅ Documentation updated (Task 14)
6. ✅ No open P0/P1 bugs related to faster-whisper backend
7. ✅ Operator feedback period (minimum 2 weeks opt-in usage)

**Decision authority:** Maintainer approval required after evidence review.

**Timeline:** Not part of this plan. Default switch is a separate future decision.

---

## Summary

- **Supported now:** transformers on Linux/macOS/Windows (CPU/CUDA, MPS unverified)
- **Target support:** faster-whisper on Linux/macOS/Windows (CPU/CUDA, no MPS)
- **Unsupported:** faster-whisper + MPS, Python < 3.10
- **Rollback:** Operator-controlled via env/config/CLI, no code changes
- **Fallback:** No silent switching; explicit errors with backend context
- **Coexistence:** Both backends can be installed simultaneously
- **Default switch:** Deferred to post-validation decision (not in this plan)
