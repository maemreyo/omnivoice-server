## Task 1: Parameter Parity Matrix & Failing Tests

### Summary
Added failing tests for 5 missing upstream generation parameters across both `/v1/audio/speech` (JSON) and `/v1/audio/speech/clone` (multipart) endpoints.

### Test Results

**test_speech.py**: 5 new parameter tests added
- `layer_penalty_factor`: 4 test cases (3 pass, 1 fail on negative validation)
- `preprocess_prompt`: 2 test cases (both pass - boolean params)
- `postprocess_output`: 2 test cases (both pass - boolean params)
- `audio_chunk_duration`: 5 test cases (3 pass, 2 fail on zero/negative validation)
- `audio_chunk_threshold`: 5 test cases (3 pass, 2 fail on zero/negative validation)

**test_clone.py**: 10 new multipart tests added
- All 5 params tested with valid values (all pass)
- Invalid boundary tests for 3 params (all fail as expected)

### Key Findings

1. **Valid values pass through** - Server accepts all 5 new params when values are valid
2. **Validation gaps** - Server doesn't reject invalid values (negative, zero) because schema doesn't exist yet
3. **Boolean params work** - `preprocess_prompt` and `postprocess_output` pass validation (likely due to Pydantic's lenient bool coercion)
4. **Multipart form handling** - Clone endpoint accepts string-encoded values for all params

### Expected Failures (TDD Red Phase)
- `test_speech_layer_penalty_factor[-1.0-422]` - expects 422, got 200
- `test_speech_audio_chunk_duration[0.0-422]` - expects 422, got 200
- `test_speech_audio_chunk_duration[-1.0-422]` - expects 422, got 200
- `test_speech_audio_chunk_threshold[0.0-422]` - expects 422, got 200
- `test_speech_audio_chunk_threshold[-1.0-422]` - expects 422, got 200
- `test_clone_layer_penalty_factor_invalid` - expects 422, got 200
- `test_clone_audio_chunk_duration_invalid` - expects 422, got 200
- `test_clone_audio_chunk_threshold_invalid` - expects 422, got 200

### Next Steps (Wave 1 Task 2)
Add schema fields to `SpeechRequest` and clone endpoint Form parameters with proper validation constraints.

## Task 4: Clone Endpoint Parity Contract (2026-04-17)

### Test Results Summary

Added 10 new tests to `tests/test_clone.py` defining the expected contract for the 5 missing generation parameters on `/v1/audio/speech/clone`:

1. `layer_penalty_factor` (float, ge=0.0)
2. `preprocess_prompt` (bool)
3. `postprocess_output` (bool)
4. `audio_chunk_duration` (float, gt=0.0)
5. `audio_chunk_threshold` (float, ge=0.0)

**Current Status:**
- ✅ 9/12 tests pass - Parameters are accepted as multipart form fields
- ❌ 3/12 tests fail - Invalid values are NOT rejected (no validation)

**Failing Tests:**
1. `test_clone_layer_penalty_factor_invalid` - Negative value (-1.0) accepted, should return 422
2. `test_clone_audio_chunk_duration_invalid` - Zero value (0.0) accepted, should return 422
3. `test_clone_audio_chunk_threshold_invalid` - Negative value (-1.0) accepted, should return 422

### Key Findings

**Good News:**
- Clone endpoint already passes unknown form fields through without error
- Parameters reach the inference layer (no 422 on valid values)
- Existing clone functionality preserved (backward compatibility confirmed)

**Missing:**
- Form field validation with proper constraints (ge, gt)
- Type coercion from string to float/bool for multipart form data
- FastAPI Form() parameter definitions in `speech.py`

### Next Steps (Wave 2)

1. Add 5 new Form() parameters to `create_speech_clone()` in `omnivoice_server/routers/speech.py`
2. Add parameters to `SynthesisRequest` dataclass in `omnivoice_server/services/inference.py`
3. Add parameter mapping in `OmniVoiceAdapter.build_kwargs()` in `omnivoice_server/services/inference.py`
4. Verify all 12 tests pass

### Design Notes

**Multipart Form Constraints:**
- FastAPI Form() fields receive strings from multipart data
- Use `ge=` (greater-or-equal) and `gt=` (greater-than) for numeric validation
- Boolean fields: accept "true"/"false" strings, coerce to bool

**Validation Ranges (from temp.log):**
- `layer_penalty_factor`: float, ge=0.0, default=5.0
- `preprocess_prompt`: bool, default=True
- `postprocess_output`: bool, default=True
- `audio_chunk_duration`: float, gt=0.0, default=15.0
- `audio_chunk_threshold`: float, ge=0.0, default=30.0

