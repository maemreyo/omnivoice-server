# Summary: Fix Script Synthesis

## Task Completed Successfully ✅

Fixed `services/script.py` and completely rewrote `routers/script.py` to match API spec v1.1.

## Changes Summary

### services/script.py
- Added `import torch` at module level (line 15)
- Fixed `_synthesize_segments` to store raw tensors instead of base64
- Changed to concatenate tensors: `torch.cat(synthesis_result.tensors, dim=-1)`
- Store `duration_s` (not `duration_ms`)
- Fixed pause segments to use `duration_s` (not `duration_ms`)

### routers/script.py
- Complete rewrite with correct field names:
  - `script` (not `segments`)
  - `output_format` (not `output_mode`)
  - `pause_between_speakers` (not `pause_s`)
  - `on_error` default `"abort"` (not `"skip"`)
- Created `_ScriptAdapterRequest` dataclass for clean interface mapping
- Removed all base64 decoding - work directly with tensors
- Import `SAMPLE_RATE` from `utils.audio`
- Removed `X-Speakers` header (only `X-Speakers-Unique` per spec v1.1)
- Cleaned up all unnecessary comments

## Verification Results

✅ `lsp_diagnostics` clean on both files (0 errors)
✅ Python imports successful
✅ Field names validated correct
✅ Tensor handling verified
✅ Audio utilities work correctly
✅ No references to old field names
✅ Service layer output structure correct

## Key Architecture

**Service Layer Output:**
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

**Router Adapter:**
```python
@dataclass
class _ScriptAdapterRequest:
    segments: list  # maps from body.script
    default_voice: str | None
    speed: float
    on_error: str
    insert_pause_ms: int
```

Task completed at: 2026-04-17T16:05:03Z
