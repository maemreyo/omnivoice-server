# Learnings: Fix Script Synthesis

## Changes Made

### 1. Fixed `services/script.py` - `_synthesize_segments` method
- **Problem**: Stored wrong type - tried to access non-existent fields `audio_base64` and `duration_ms` on `SynthesisResult`
- **Solution**: 
  - Added `import torch` at module level
  - Changed to concatenate raw tensors: `torch.cat(synthesis_result.tensors, dim=-1)`
  - Store dict with `"audio": audio_tensor` (torch.Tensor) instead of base64 string
  - Use `duration_s` field (not `duration_ms`)
  - Removed unnecessary inline imports and comments

### 2. Completely rewrote `routers/script.py`
- **Problem**: Wrong field names, wrong architecture, unnecessary base64 encoding/decoding
- **Solution**:
  - Changed request body fields to match spec:
    - `script` (not `segments`)
    - `output_format` (not `output_mode`)
    - `pause_between_speakers` (not `pause_s`)
    - `on_error` default `"abort"` (not `"skip"`)
  - Created `_ScriptAdapterRequest` dataclass for orchestrator interface mapping
  - Removed all base64 decoding logic - work directly with tensors from service layer
  - Removed `X-Speakers` header (only `X-Speakers-Unique` allowed per v1.1 spec)
  - Import `SAMPLE_RATE` from `utils.audio` for duration calculation
  - Cleaned up all unnecessary comments

## Key Interface Contracts

### SynthesisResult (from InferenceService)
```python
@dataclass
class SynthesisResult:
    tensors: list  # list[torch.Tensor], each (1, T)
    duration_s: float
    latency_s: float
```

### Service Layer Output
```python
{
    "type": "audio",
    "index": int,
    "speaker": str,
    "audio": torch.Tensor,  # (1, T) raw tensor
    "duration_s": float,
    "voice": str,
}
```

### Router Adapter Pattern
- Use dataclass `_ScriptAdapterRequest` to map body fields to orchestrator interface
- Maps `body.script` → `adapter.segments`
- Maps `body.pause_between_speakers * 1000` → `adapter.insert_pause_ms`

## Verification Status
- ✅ `lsp_diagnostics` clean on both files
- ✅ Python imports successful
- ✅ Field names verified correct
- ⚠️ mypy warnings exist in original code (not introduced by this change)
