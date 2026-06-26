# ASR Assumptions Inventory - Executive Summary

**Task**: Wave 1 Task 1 - Inventory current ASR assumptions
**Status**: ✅ COMPLETE
**Date**: 2026-04-19

---

## Inventory Scope

**Files Analyzed**: 13 core files
- 1 main model file (`OmniVoice/omnivoice/models/omnivoice.py`)
- 1 test file (`tests/test_speech.py`)
- 4 evaluation scripts (`eval/wer/*.py`)
- 3 CLI/demo files (`cli/*.py`)
- 3 server integration files (`omnivoice_server/**/*.py`)
- 1 documentation file (`OmniVoice/README.md`)

**Lines of Code Reviewed**: ~3,500 lines directly related to ASR

---

## Key Findings

### 1. Single Choke Point Architecture ✅
- **ALL** auto-transcription flows through `OmniVoice.transcribe()` (lines 314-346)
- ASR logic isolated in 2 methods: `load_asr_model()` and `transcribe()`
- No ASR-specific logic scattered across codebase
- **Impact**: Clean abstraction point for migration

### 2. Critical Coupling Points 🔴
1. **Model name format**: `"openai/whisper-large-v3-turbo"` (transformers) vs `"large-v3-turbo"` (faster-whisper)
2. **Transcript return shape**: `{"text": "..."}` dict vs `(segments, info)` tuple
3. **Device handling**: `device_map=torch.device` vs `device="cuda"` string
4. **Lazy loading contract**: `_asr_pipe=None` → trigger load on `ref_text=None`
5. **Error handling contract**: torchcodec failure → warning + None (no exception)

### 3. Test Coverage Gap 🔴
- **ZERO** tests exercise actual ASR pipeline
- All tests mock inference service → ASR never called
- No baseline for equivalence testing
- **Impact**: HIGH RISK for migration without new tests

### 4. Hidden Assumptions 🟡
1. `ref_text=None` is ONLY trigger for auto-transcription
2. No alternative ASR backend configured
3. Transcript used directly in prompt construction (no validation)
4. Batch inference: all-or-nothing `ref_text` handling
5. No ASR availability check at API validation layer

---

## Migration-Critical Surfaces

### MUST Preserve (Backward Compatibility)
1. ✅ Lazy loading behavior: `_asr_pipe=None` → load on demand
2. ✅ Error handling: torchcodec failure → warning + None
3. ✅ Transcript format: plain string output
4. ✅ Auto-transcription trigger: `ref_text=None`
5. ✅ RuntimeError when ASR unavailable

### MUST Update (Technical Requirements)
1. 🔧 Model name format: Add translation layer
2. 🔧 Pipeline initialization: transformers → faster-whisper
3. 🔧 Transcribe call signature: Normalize return format
4. 🔧 Device handling: Convert torch.device → string

### MUST Test (Quality Assurance)
1. 🧪 `ref_text=None` → auto-transcription path
2. 🧪 Lazy loading on-demand
3. 🧪 ASR unavailable → RuntimeError
4. 🧪 Transcript format matches expected shape
5. 🧪 Clone workflow with auto-transcription
6. 🧪 Batch inference with mixed ref_text values

---

## Issues Discovered

### HIGH Severity (Blockers)
1. **Model name format mismatch** - Migration blocker, needs translation layer
2. **No direct ASR tests** - No baseline for equivalence, HIGH RISK

### MEDIUM Severity (Must Address)
3. **Transcript return format coupling** - Abstraction must normalize
4. **No ASR availability check at API layer** - Poor error UX (500 vs 422)
5. **Device handling differences** - Abstraction must convert types

### LOW Severity (Can Defer)
6. **Batch inference mixed ref_text handling** - Unexpected behavior, document
7. **Evaluation scripts share dependency** - Not production-critical
8. **Demo UI no ASR feedback** - UX improvement, not blocker
9. **Documentation missing torchcodec mention** - Update after migration
10. **Lazy loading error handling inconsistency** - Minor UX issue

---

## Architectural Decisions

### Confirmed by Inventory
1. ✅ **Single abstraction point** - `load_asr_model()` and `transcribe()` only
2. ✅ **Preserve lazy loading contract** - Exact same behavior required
3. ✅ **Preserve error handling contract** - Two-phase error handling
4. ✅ **Transformers default first** - Opt-in faster-whisper initially
5. ✅ **Evaluation scripts out of scope** - Defer to Wave 2

### Required by Inventory
6. 🔧 **Model name translation layer** - Accept both formats
7. 🔧 **Transcript format normalization** - Plain string output
8. 🔧 **Device handling normalization** - Convert types, handle MPS
9. 🧪 **Fixture-based equivalence testing** - Before default switch
10. 📋 **API validation deferred** - Wave 2 enhancement

---

## Open Questions (Blocking Wave 1 Task 2)

### Critical (Must Resolve for Abstraction Design)
1. **Backend selection mechanism** - Env var? Kwarg? Auto-detect?
2. **Dependency management** - Both required? Optional extras?
3. **Model name backward compatibility** - Translate? Deprecate? Break?
4. **MPS device handling** - Silent fallback? Error? Try-catch?
5. **Lazy loading with multiple backends** - When to select backend?
6. **Error message consistency** - Keep same? Update? Backend-specific?

### Important (Must Resolve for Equivalence Testing)
7. **Fixture generation strategy** - Which audio samples to use?
8. **Equivalence threshold definition** - WER < 5%? < 10%? Exact match?

### Planning (Must Resolve for Wave 1 Overall)
9. **Testing strategy for server integration** - Mock? Real? Fixtures?
10. **Migration timeline and rollout** - When to switch default?

---

## Out of Scope (Not Migration-Relevant)

### Deferred to Wave 2+
- Evaluation scripts (seedtts.py, hubert.py, minimax.py, fleurs.py)
- Server API validation enhancement (422 vs 500 errors)
- Demo UI ASR availability feedback
- Documentation updates (after migration proven)
- Batch inference per-item ASR control

### Not Affected by Migration
- Profile storage/retrieval (profiles.py)
- API request/response models (routers/*.py)
- Server startup/shutdown logic
- Voice preset mappings
- Audio format conversion

---

## Next Steps (Wave 1 Task 2)

### Immediate Actions Required
1. 🎯 **Design ASRBackend protocol** - Define interface contract
2. 🎯 **Resolve open questions 1-6** - Backend selection, dependencies, etc.
3. 🎯 **Create abstraction layer** - TransformersASR and FasterWhisperASR
4. 🎯 **Add model name translation** - Accept both formats
5. 🎯 **Normalize transcript format** - Plain string output
6. 🎯 **Normalize device handling** - Convert types, handle MPS

### Preparation for Task 3
7. 📋 **Resolve open questions 7-8** - Fixtures, equivalence threshold
8. 📋 **Generate test fixtures** - Record transformers transcripts
9. 📋 **Define equivalence criteria** - WER threshold, test cases

### Documentation
10. 📝 **Update architecture docs** - Document abstraction design
11. 📝 **Create migration guide** - For users and developers

---

## Metrics

**Total Surfaces Identified**: 11 major categories
**Migration-Critical Surfaces**: 5 (model loading, transcription, CLI, docs, server)
**Test Gaps**: 6 (no ASR tests, no failure mode tests, no format validation)
**Documentation Gaps**: 2 (no torchcodec mention, no Windows limitations)
**Issues Found**: 10 (2 HIGH, 3 MEDIUM, 5 LOW)
**Decisions Made**: 10 architectural decisions
**Open Questions**: 10 blocking questions

**Confidence Level**: HIGH
- Comprehensive inventory completed
- All major surfaces identified
- Clear migration path defined
- Risks and blockers documented

---

## Risk Assessment

### HIGH RISK ⚠️
- No existing ASR tests → Need fixture-based equivalence tests
- Model name format mismatch → Need translation layer
- Transcript format coupling → Need normalization layer

### MEDIUM RISK ⚠️
- Device handling differences → Need type conversion
- MPS device unsupported → Need fallback strategy
- Lazy loading with multiple backends → Need clear contract

### LOW RISK ✅
- Single abstraction point → Clean migration path
- Isolated ASR logic → No scattered changes
- Clear error handling contract → Easy to preserve

**Overall Risk**: MEDIUM (manageable with proper testing)

---

## Conclusion

✅ **Inventory Complete**: All ASR assumptions documented
✅ **Migration Path Clear**: Single abstraction point identified
✅ **Risks Identified**: 10 issues documented with severity
✅ **Decisions Made**: 10 architectural decisions confirmed
⚠️ **Blockers Identified**: 10 open questions must be resolved

**Ready for Wave 1 Task 2**: Abstraction design can proceed with clear requirements.

**Recommendation**: Resolve critical open questions (1-6) before starting abstraction implementation. Create fixture-based equivalence tests (questions 7-8) in parallel with abstraction design.
