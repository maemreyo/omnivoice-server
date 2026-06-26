# Decisions: Fix Script Synthesis

## Architecture Decisions

### 1. Store Raw Tensors in Service Layer
**Decision**: Store `torch.Tensor` objects directly in `synthesized_segments` list instead of base64-encoded strings.

**Rationale**:
- Avoids unnecessary encoding/decoding overhead
- Service layer should work with native data types
- Router layer handles serialization for HTTP response
- Cleaner separation of concerns

### 2. Use Dataclass Adapter Pattern
**Decision**: Create `_ScriptAdapterRequest` dataclass to map router body to orchestrator interface.

**Rationale**:
- Avoids anonymous objects created with `type()`
- Type-safe and explicit
- Easy to understand and maintain
- Follows Python best practices

### 3. Field Name Alignment with Spec
**Decision**: Use exact field names from spec v1.1:
- `script` (not `segments`)
- `output_format` (not `output_mode`)
- `pause_between_speakers` (not `pause_s`)
- `on_error` default `"abort"` (not `"skip"`)

**Rationale**:
- API contract must match documentation
- Prevents client confusion
- Follows OpenAI-compatible naming conventions

### 4. Remove X-Speakers Header
**Decision**: Only include `X-Speakers-Unique` header, not `X-Speakers`.

**Rationale**:
- Spec v1.1 explicitly removed `X-Speakers`
- Avoid redundant headers
- `X-Speakers-Unique` provides the needed information

## Implementation Notes

### Tensor Concatenation
- `SynthesisResult.tensors` is a list because long texts may be split into chunks
- Must concatenate with `torch.cat(tensors, dim=-1)` to get single tensor
- Shape is `(1, T)` where T is total samples

### Duration Calculation
- Use `SAMPLE_RATE = 24_000` from `utils.audio`
- Formula: `duration_s = tensor.shape[-1] / SAMPLE_RATE`
- Service layer stores `duration_s` (not `duration_ms`)
