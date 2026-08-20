# Multi-Speaker Script API - Learnings

## Task 4: Script Router Implementation (2026-04-17)

### Pattern: FastAPI Router with Pydantic Validation
- Used `@field_validator` for custom speaker ID regex validation
- Validator runs at request parsing time (before endpoint logic)
- Clear error messages: "Invalid speaker ID '{id}': must be 1-64 alphanumeric/underscore/hyphen characters"

### Pattern: Dependency Injection
- `_get_orchestrator(request: Request) -> ScriptOrchestrator`
- Injected via `Depends()` in endpoint signature
- Avoids circular imports by accessing `request.app.state.script_orchestrator`

### Pattern: Audio Processing Pipeline
- Decode base64 → convert to tensors → mix/group → encode to format
- `mix_to_single_track()` returns tuple of (tensor, timestamps)
- `group_by_speaker()` returns dict of speaker → concatenated tensor
- Router handles final mixing (NOT orchestrator) to avoid circular imports

### Pattern: Response Headers
- X-Audio-Duration-S, X-Synthesis-Latency-S, X-Speakers-Unique, X-Segment-Count, X-Skipped-Segments
- Empty X-Skipped-Segments header when no segments skipped (not omitted)

### Validation Strategy
- Pydantic handles: field types, min/max lengths, numeric ranges
- Custom validators handle: regex patterns, cross-field validation (total chars, unique speakers)
- Orchestrator handles: voice resolution, profile existence, synthesis errors

## Python Version Compatibility Patterns

**Date**: 2026-04-17

**Lesson**: Always check Python version compatibility for async features.

**Key Findings**:
- `asyncio.timeout()` context manager was added in Python 3.11
- `asyncio.wait_for()` is the Python 3.9+ compatible alternative
- Both provide timeout functionality but with different APIs

**Pattern for Timeout Handling**:
```python
# Python 3.11+ only:
async with asyncio.timeout(timeout_seconds):
    result = await some_coroutine()

# Python 3.9+ compatible:
try:
    result = await asyncio.wait_for(some_coroutine(), timeout=timeout_seconds)
except asyncio.TimeoutError:
    # Handle timeout
    pass
```

**Best Practice**: When targeting Python 3.9, use `asyncio.wait_for()` for timeout handling. Document the compatibility constraint with inline comments to prevent future "modernization" that breaks compatibility.

**Testing Strategy**: The test suite caught this issue immediately because conftest.py runs on Python 3.9.6. All 24 script tests failed with the same import error, making the root cause obvious.

