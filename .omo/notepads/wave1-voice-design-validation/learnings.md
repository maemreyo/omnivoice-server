# Task 2: Instruction Validation Tests - Learnings

## Test Results Summary

**Date**: 2026-04-17T04:35:44Z

### Failing Tests (Expected Behavior)

Successfully added 19 failing tests that define the validation spec:

1. **Unsupported emotion attributes** (7 tests) - All failing as expected:
   - `cheerful`, `sad`, `angry`, `surprised`, `happy`, `fearful`, `disgusted`
   - Currently return 200, should return 422

2. **Unsupported speaking style attributes** (4 tests) - All failing as expected:
   - `narration`, `customer_service`, `news_presentation`, `sportscasting`
   - Currently return 200, should return 422

3. **Conflicting categories** (3 tests) - All failing as expected:
   - `male,female` (gender conflict)
   - `child,elderly` (age conflict)
   - `very low pitch,very high pitch` (pitch conflict)
   - Currently return 200, should return 422

4. **Empty instructions** (2 tests) - Failing as expected:
   - Empty string `""`
   - Whitespace only `"   "`
   - Currently return 200, should return 422

5. **Accent alias canonicalization** (1 test) - Failing as expected:
   - `british` should be canonicalized to `british accent`
   - Currently passes through unchanged

6. **Error message validation** (2 tests) - Failing as expected:
   - Unsupported emotion error message test
   - Conflict error message test

### Passing Tests (Baseline Behavior)

27 tests passing, confirming current behavior:

1. **Valid canonical instructions** (7 tests):
   - Single attributes: `female`, `british accent`, `young adult`, `high pitch`, `whisper`
   - Combined: `female,british accent,young adult,high pitch`
   - Default preset: `male,middle-aged,moderate pitch,american accent`

2. **Short accent aliases** (10 tests):
   - All 10 accent aliases pass through without validation
   - `british`, `american`, `australian`, `canadian`, `indian`, `chinese`, `korean`, `japanese`, `portuguese`, `russian`

3. **Duplicate handling** (2 tests):
   - `female,female` - duplicates accepted
   - `british accent,british accent` - duplicates accepted

4. **Chinese dialect** (1 test):
   - `四川话` accepted correctly

### Key Findings

1. **No validation exists yet** - All instructions are currently accepted (200 status)
2. **Accent aliases not canonicalized** - Short forms like `british` pass through unchanged
3. **No conflict detection** - Multiple values from same category accepted
4. **Empty instructions accepted** - No validation for empty/whitespace-only strings
5. **No error messages** - 422 responses not implemented yet

### Test Coverage

Total instruction validation tests: 45
- Parametrized validation tests: 34
- Specific behavior tests: 5
- Existing preset tests: 6

### Next Steps (Task 3)

Implement validation logic in `omnivoice_server/routers/speech.py`:
1. Parse and validate instructions against `DESIGN_ATTRIBUTES`
2. Canonicalize accent aliases (e.g., `british` → `british accent`)
3. Detect conflicts within categories
4. Reject unsupported attributes with actionable error messages
5. Handle empty/whitespace-only instructions
