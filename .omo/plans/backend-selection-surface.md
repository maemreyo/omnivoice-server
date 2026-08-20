# Backend Selection Surface Design Document

**Task**: Define backend selection surface across library/server/CLI  
**Date**: 2026-04-19  
**Status**: COMPLETE

---

## Control Surface

**Multi-Layer Selection with Precedence**:

1. **CLI flag**: `--asr-backend transformers|faster-whisper` (highest priority)
2. **Environment variable**: `OMNIVOICE_ASR_BACKEND=transformers|faster-whisper`
3. **Config file**: `asr_backend: transformers|faster-whisper` (server only)
4. **Default**: `transformers` (lowest priority)

**Precedence Rule**: CLI flag > Environment variable > Config file > Default

**Valid Values**:
- `transformers` (default) - HuggingFace transformers Whisper pipeline
- `faster-whisper` - CTranslate2-based faster-whisper backend

**Default Behavior**: If no selector provided at any layer, defaults to `transformers`

**Validation**: Invalid values raise `ValueError` with clear error message at config/model load time

---

## Integration Points

### 1. Server Configuration

**File**: `omnivoice_server/config.py`

**Addition**:
```python
class Settings(BaseSettings):
    # ... existing fields ...
    
    asr_backend: Literal["transformers", "faster-whisper"] = Field(
        default="transformers",
        description="ASR backend for auto-transcription",
    )
```

**Behavior**:
- Reads from `OMNIVOICE_ASR_BACKEND` env var via Pydantic settings
- Validated at Settings instantiation
- Logged at server startup
- Passed to OmniVoice model initialization

### 2. Library (OmniVoice Model)

**File**: `OmniVoice/omnivoice/models/omnivoice.py`

**Integration**:
- `from_pretrained()` reads `OMNIVOICE_ASR_BACKEND` env var
- Backend factory/selector chooses appropriate adapter
- Lazy initialization on first `transcribe()` call with `ref_text=None`

**Behavior**:
- Backend selection logged at model load time
- Backend adapter loaded lazily on first use
- Clear error if selected backend unavailable

### 3. CLI/Demo

**Files**: 
- `OmniVoice/omnivoice/cli/demo.py`
- `OmniVoice/omnivoice/cli/infer.py`
- `omnivoice_server/cli.py`

**Addition**:
```python
parser.add_argument(
    "--asr-backend",
    default=None,
    choices=["transformers", "faster-whisper"],
    help="ASR backend for auto-transcription (env: OMNIVOICE_ASR_BACKEND)",
)
```

**Behavior**:
- CLI flag `--asr-backend` overrides environment variable
- If CLI flag not provided, falls back to `OMNIVOICE_ASR_BACKEND` env var
- If neither provided, uses config file or default

### 4. Tests

**Integration**:
```python
def test_with_transformers(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_ASR_BACKEND", "transformers")
    # test code

def test_with_faster_whisper(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_ASR_BACKEND", "faster-whisper")
    # test code
```

**Behavior**:
- Pytest `monkeypatch.setenv()` provides deterministic control
- Parametrized tests can run same scenarios against both backends
- CI matrix can test both backends explicitly

---

## Rollback Mechanism

**Operator Actions** (choose one method):

**Method 1: CLI Flag** (highest priority, immediate)
```bash
omnivoice-server --asr-backend transformers
```

**Method 2: Environment Variable**
```bash
export OMNIVOICE_ASR_BACKEND=transformers
# Restart server/process
```

**Method 3: Config File** (server only)
```yaml
# config.yaml or .env
asr_backend: transformers
# Restart server/process
```

**Verification**:
- Check logs for "ASR backend: transformers"
- Run clone mode test with `ref_text=None`
- Verify transcript generation succeeds

**Requirements Met**:
- ✓ No code changes required
- ✓ Multiple rollback paths available (operator choice)
- ✓ Same mechanism as forward selection
- ✓ Deterministic and repeatable
- ✓ Evidence captured in logs

---

## Rollout Strategy

### Phase 1 (Current)
- **Default**: `transformers` (preserves current behavior)
- **Opt-in**: `faster-whisper` via `OMNIVOICE_ASR_BACKEND=faster-whisper`
- **Goal**: Validate faster-whisper in production environments

### Phase 2 (Future)
- After validation period, consider switching default to `faster-whisper`
- `transformers` remains available for rollback
- Announcement and migration guide provided

### Always
- Both backends remain available
- Rollback always possible via env var
- No forced migration

---

## Validation Rules

**At Config Load**:
- Backend value validated against allowed values
- Clear error: `"Invalid ASR backend '{value}'. Must be 'transformers' or 'faster-whisper'."`

**At Backend Load**:
- Backend dependency availability checked
- Missing dependency produces actionable error with install instructions
- Example: `"faster-whisper backend selected but package not installed. Run: pip install faster-whisper"`

**At Runtime**:
- Backend selection logged clearly
- Transcription errors include backend context
- Fallback behavior follows documented policy

---

## Consistency Guarantees

**Same Mechanism Everywhere**:
- Library: reads `OMNIVOICE_ASR_BACKEND` env var (or kwarg override)
- Server: reads via Pydantic Settings with precedence: CLI > env > config > default
- CLI/Demo: `--asr-backend` flag overrides env var
- Tests: override via `monkeypatch.setenv()`

**Same Backend Names**:
- `transformers` - consistent across all surfaces
- `faster-whisper` - consistent across all surfaces
- No surface-specific aliases or variations

**Same Validation**:
- Invalid values rejected at config/load time
- Same error messages across surfaces
- Same logging format across surfaces

---

## Design Rationale

**Why Multi-Layer Precedence?**
- Provides flexibility: operators choose CLI (immediate) or env/config (persistent)
- Consistent with existing `OMNIVOICE_*` pattern (env vars + CLI overrides)
- Works across all runtime surfaces without code changes
- Easy to override in tests (env var layer)
- Operator-friendly rollback (multiple methods available)

**Why Not Single Layer Only?**
- CLI-only: doesn't help library usage or persistent config
- Env-only: less flexible for immediate overrides
- Config-only: harder to override in tests, less operator-friendly for quick rollback

**Why Not Auto-Detection?**
- Violates determinism requirement
- Makes rollback unpredictable
- Harder to debug issues
- Conflicts with explicit operator control

---

## Implementation Checklist

- [ ] Add `asr_backend` field to `omnivoice_server/config.py` (reads from env)
- [ ] Add `--asr-backend` CLI flag to `omnivoice_server/cli.py`
- [ ] Add `--asr-backend` CLI flag to `OmniVoice/omnivoice/cli/demo.py`
- [ ] Add `--asr-backend` CLI flag to `OmniVoice/omnivoice/cli/infer.py`
- [ ] Implement precedence logic: CLI > env > config > default
- [ ] Add backend selection to OmniVoice model initialization
- [ ] Add backend factory/selector logic
- [ ] Add validation for backend values at each layer
- [ ] Add logging for backend selection (show which layer was used)
- [ ] Update tests to use `monkeypatch.setenv()` for env layer
- [ ] Document rollback procedure (all three methods)
- [ ] Add error messages for missing dependencies

---

## Success Criteria

✓ Single documented backend selection policy exists (multi-layer precedence)
✓ Works across library, server, CLI, tests  
✓ Tests can force each backend deterministically (via env layer)
✓ Rollback available via CLI/env/config (operator choice, no code changes)
✓ Backend selection logged and observable (shows which layer was used)
✓ Invalid values produce clear errors at each layer
✓ Consistent naming across all surfaces
✓ Precedence rule explicit: CLI > env > config > default  

---

**Document Status**: FINAL  
**Next Steps**: Implementation in Wave 2 tasks (backend adapters and integration)
