# OmniVoice Upstream Alignment Plan

## TL;DR

> **Quick Summary**: Align `omnivoice-server` more tightly with upstream OmniVoice by exposing the remaining documented generation parameters, adding API-layer validation/canonicalization for supported voice-design instructions, keeping `/v1/audio/speech` and `/v1/audio/speech/clone` in sync, and updating tests/docs without breaking existing valid clients.
>
> **Deliverables**:
> - Expose missing upstream generation parameters across request schemas, internal request mapping, config/default handling where appropriate, and clone endpoint parity
> - Add server-side validation/canonicalization for `instructions` using upstream-compatible allowlists and conflict rules
> - Update voice metadata/docs/examples to reflect canonical supported attributes and clearly label server-only extensions
> - Add/adjust automated tests to lock behavior down
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves + final verification
> **Critical Path**: Task 1 → Task 5 → Task 9 → F1-F4

---

## Context

### Original Request
Check `temp.log`, compare prior verdicts against upstream OmniVoice docs, then create a plan so the user can implement the necessary `omnivoice-server` alignment work.

### Interview Summary
**Key Discussions**:
- User cross-checked previous verdicts with upstream `voice-design.md` and `generation-parameters.md`.
- User confirmed prior analysis was largely correct, but flagged one missing documented upstream parameter in the verdict write-up: `denoise`.
- Codebase inspection showed `denoise` is already exposed in this server, so the real implementation gap is broader upstream alignment.
- User recommended four tiers: upstream param exposure, voice-design validation, explicit labeling of server-only extensions, and future upstream tracking.
- User approved proceeding after recommendation defaults were proposed.

**Research Findings**:
- Main request schema and clone form live in `omnivoice_server/routers/speech.py`.
- Internal argument translation seam is `omnivoice_server/services/inference.py::OmniVoiceAdapter.build_kwargs()`.
- Voice preset catalog and client-facing attribute exposure live in `omnivoice_server/voice_presets.py` and `omnivoice_server/routers/voices.py`.
- Current code already exposes `num_step`, `guidance_scale`, `denoise`, `t_shift`, `position_temperature`, `class_temperature`, `duration`, `speed`, `language`, and `instructions`.
- Current code does not expose these upstream-documented knobs from `temp.log`: `layer_penalty_factor`, `preprocess_prompt`, `postprocess_output`, `audio_chunk_duration`, `audio_chunk_threshold`.
- `/v1/audio/speech/clone` duplicates generation parameter handling and must remain aligned.
- Server currently does not validate `instructions`; upstream validates strictly.
- Test infra already exists and is TDD-ready via pytest, coverage, mypy, ruff, and CI.

### Metis Review
**Identified Gaps** (addressed):
- Backward compatibility ambiguity: resolved by preserving current behavior for existing valid requests and limiting strict failures to invalid `instructions` and invalid new parameter values.
- Scope creep risk around CLI/config/SDK: resolved by limiting scope to targeted parity review and only changing CLI/config surfaces when directly required by the new parameter exposure.
- Acceptance criteria clarity: resolved by adding concrete schema, validation, docs, and test verification requirements.
- Edge-case risk for instruction normalization/conflicts: resolved by explicitly planning conflict, duplicate, short-vs-full accent, and mixed-validity handling.

---

## Work Objectives

### Core Objective
Bring `omnivoice-server` into closer upstream alignment by exposing the remaining documented generation controls and enforcing a clear, user-friendly, upstream-compatible instruction validation layer, while preserving compatibility for existing valid traffic.

### Concrete Deliverables
- Request-schema support for `layer_penalty_factor`, `preprocess_prompt`, `postprocess_output`, `audio_chunk_duration`, and `audio_chunk_threshold`
- Matching internal request/mapping support through `OmniVoiceAdapter.build_kwargs()`
- Clone endpoint parity for the same generation parameters
- Canonical instruction validation/canonicalization utilities grounded in upstream-supported voice-design attributes
- Updated voice metadata surface and documentation/examples
- Regression tests covering valid/invalid request paths and endpoint parity

### Definition of Done
- [ ] `POST /v1/audio/speech` accepts the five missing upstream-documented parameters with validated types/ranges and passes them to the inference layer
- [ ] `POST /v1/audio/speech/clone` supports the same relevant generation parameters as multipart form fields where supported by the endpoint
- [ ] Invalid or conflicting `instructions` fail fast with actionable 4xx responses
- [ ] Supported accent variants are accepted, canonicalized to full `... accent` forms, and serialized/documented consistently
- [ ] `GET /v1/voices` and docs accurately reflect supported attributes only
- [ ] Automated tests pass and cover the newly enforced behavior

### Must Have
- Upstream-documented missing parameters exposed on server API surfaces that already expose generation controls
- Voice-design validation aligned with upstream-supported categories only
- Backward compatibility for existing valid requests and preset usage
- Clear labeling of server-only features/extensions vs upstream-native OmniVoice capabilities
- Main speech + clone parity review and synchronization

### Must NOT Have (Guardrails)
- Do not add unsupported emotion/speaking-style attributes such as `cheerful`, `sad`, `angry`, `surprised`, `narration`, or `customer_service`
- Do not invent a separate `phoneme_input` parameter; pronunciation control remains inline in `text`
- Do not refactor unrelated streaming/auth/profile systems just because adjacent files are touched
- Do not break existing valid preset names or valid request payloads
- Do not silently accept unsupported `instructions` once API-layer validation is added
- Do not relabel custom server extensions as native upstream OmniVoice features

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: TDD
- **Framework**: pytest + pytest-cov
- **If TDD**: Each implementation task should begin by extending/failing the relevant pytest coverage before code changes, then making the minimum code change to pass.

### QA Policy
Every task must include agent-executed QA scenarios with evidence artifacts under `.sisyphus/evidence/`.

- **API/Backend**: Use Bash with `curl` or pytest invocation and inspect status codes / JSON payloads / output files
- **Library/Module**: Use pytest or a targeted Python invocation to verify canonicalization/validation helpers
- **Docs/Metadata**: Use Read/Grep assertions to confirm canonical lists and custom-extension labeling are present

---

## Execution Strategy

### Parallel Execution Waves

Wave 1 (Start Immediately - foundation + independent test scaffolding):
├── Task 1: Parameter parity matrix + failing schema tests [quick]
├── Task 2: Upstream instruction allowlist/canonicalization spec + failing validation tests [quick]
├── Task 3: Docs/custom-extension inventory + failing docs assertions checklist [writing]
└── Task 4: Clone endpoint parity audit + failing clone tests [quick]

Wave 2 (After Wave 1 - independent implementation lanes):
├── Task 5: Main speech endpoint + inference mapping for missing generation params (depends: 1) [unspecified-high]
├── Task 6: Instruction validation/canonicalization implementation (depends: 2) [deep]
├── Task 7: Voice metadata/preset exposure alignment (depends: 2, 3) [quick]
└── Task 8: Clone endpoint parameter parity implementation (depends: 4, 5) [unspecified-high]

Wave 3 (After Wave 2 - integration + public contract consistency):
├── Task 9: README/API/examples/custom-extension labeling updates (depends: 3, 5, 6, 7, 8) [writing]
├── Task 10: Targeted CLI/config alignment review and minimal direct updates only if required by new params (depends: 5) [quick]
└── Task 11: Integration regression sweep for speech/clone/voices surfaces (depends: 5, 6, 7, 8, 10) [unspecified-high]

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1 → Task 5 → Task 8 → Task 11 → F1-F4
Parallel Speedup: ~60% faster than sequential
Max Concurrent: 4

### Dependency Matrix
- **1**: none → 5, 11, Wave 1 foundation
- **2**: none → 6, 7, 11
- **3**: none → 7, 9
- **4**: none → 8, 11
- **5**: 1 → 8, 9, 10, 11
- **6**: 2 → 9, 11
- **7**: 2, 3 → 9, 11
- **8**: 4, 5 → 9, 11
- **9**: 3, 5, 6, 7, 8 → F1-F4
- **10**: 5 → 11, F1-F4
- **11**: 5, 6, 7, 8, 10 → F1-F4

### Agent Dispatch Summary
- **Wave 1**: T1 → `quick`, T2 → `quick`, T3 → `writing`, T4 → `quick`
- **Wave 2**: T5 → `unspecified-high`, T6 → `deep`, T7 → `quick`, T8 → `unspecified-high`
- **Wave 3**: T9 → `writing`, T10 → `quick`, T11 → `unspecified-high`
- **FINAL**: F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. Build parameter parity matrix and add failing schema tests

  **What to do**:
  - Enumerate the five missing upstream generation parameters and map where each must appear: main speech request schema, clone form schema, internal synthesis request, config/default surfaces if relevant, and inference kwargs.
  - Add/extend failing pytest coverage for `POST /v1/audio/speech` validating acceptance, typing, and boundary behavior for each new parameter.
  - Explicitly define which parameters belong on clone requests vs which are main-endpoint only if multipart semantics differ.

  **Must NOT do**:
  - Do not implement runtime behavior yet.
  - Do not modify unrelated request fields.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: bounded schema-analysis + focused failing tests.
  - **Skills**: [`python-testing`, `python-patterns`]
    - `python-testing`: pytest request/validation coverage patterns.
    - `python-patterns`: clean Pydantic/FastAPI-adjacent Python changes.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: broader than necessary for a test-first schema task.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4)
  - **Blocks**: 5, 11
  - **Blocked By**: None

  **References**:
  - `temp.log` - Canonical gap list from the planning session, especially the five missing parameters.
  - `omnivoice_server/routers/speech.py` - `SpeechRequest` and clone form field definitions are the primary schema surfaces.
  - `omnivoice_server/services/inference.py` - `SynthesisRequest` and `OmniVoiceAdapter.build_kwargs()` define internal propagation targets.
  - `omnivoice_server/config.py` - Existing generation defaults pattern to follow if any new server defaults are added.
  - `tests/test_speech.py` - Existing request validation and custom parameter test style.
  - `tests/test_clone.py` - Existing multipart endpoint test style for clone parity.

  **Acceptance Criteria**:
  - [ ] New failing/updated tests exist for each missing parameter on the main speech endpoint.
  - [ ] Parameter applicability for clone endpoint is explicitly captured in tests or TODO notes within the test plan.
  - [ ] `pytest tests/test_speech.py -v` shows failures attributable only to the new missing behavior before implementation.

  **QA Scenarios**:
  ```
  Scenario: Speech schema rejects/accepts new parameter shapes as expected
    Tool: Bash (pytest)
    Preconditions: Test file updates added, no implementation yet
    Steps:
      1. Run `pytest tests/test_speech.py -v`
      2. Inspect failures for cases covering `layer_penalty_factor`, `preprocess_prompt`, `postprocess_output`, `audio_chunk_duration`, `audio_chunk_threshold`
      3. Confirm failure output points to missing schema/behavior rather than unrelated regressions
    Expected Result: New targeted tests fail before code implementation
    Failure Indicators: No new coverage exists, or failures are unrelated to planned behavior
    Evidence: .sisyphus/evidence/task-1-failing-speech-tests.txt

  Scenario: Clone parity gaps are surfaced explicitly
    Tool: Bash (pytest)
    Preconditions: Clone endpoint parity tests added
    Steps:
      1. Run `pytest tests/test_clone.py -v`
      2. Confirm newly added tests identify unsupported/missing clone parameter handling precisely
    Expected Result: Clone parity gaps are visible in isolated test failures or explicit skips with rationale
    Failure Indicators: No clone-focused coverage or ambiguous failures
    Evidence: .sisyphus/evidence/task-1-clone-gap-tests.txt
  ```

  **Commit**: NO

- [x] 8. Implement clone endpoint generation-parameter parity

  **What to do**:
  - Add the approved missing generation parameters to `/v1/audio/speech/clone` multipart handling where semantically valid.
  - Propagate clone request values through the shared synthesis request/inference path without diverging from main endpoint naming.
  - Ensure invalid multipart parameter values fail predictably and consistently.
  - Preserve existing clone-specific requirements around `ref_audio` and `ref_text`.

  **Must NOT do**:
  - Do not weaken clone file validation.
  - Do not introduce endpoint-specific parameter names unless absolutely required.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: multipart API changes with shared inference-path coordination.
  - **Skills**: [`backend-patterns`, `python-patterns`]
    - `backend-patterns`: endpoint contract parity.
    - `python-patterns`: consistent form parsing + propagation.
  - **Skills Evaluated but Omitted**:
    - `api-design`: already reflected in parity requirements; implementation is the harder part.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 7 after Task 5)
  - **Blocks**: 9, 11
  - **Blocked By**: 4, 5

  **References**:
  - `omnivoice_server/routers/speech.py` - Clone form fields and handler.
  - `omnivoice_server/services/inference.py` - Shared request propagation path.
  - `tests/test_clone.py` - Must satisfy failing tests from Task 4.
  - `tests/test_speech.py` - Use naming/validation parity as comparison.

  **Acceptance Criteria**:
  - [ ] Clone endpoint accepts the intended new parameters and forwards them correctly.
  - [ ] Invalid multipart values are rejected consistently.
  - [ ] Existing clone flows with valid reference audio continue to work.
  - [ ] `pytest tests/test_clone.py -v` passes for the new parity cases.

  **QA Scenarios**:
  ```
  Scenario: Clone endpoint accepts supported new generation params
    Tool: Bash (pytest)
    Preconditions: Clone parity implementation complete
    Steps:
      1. Run `pytest tests/test_clone.py -v`
      2. Confirm new multipart parameter cases now pass
      3. Confirm existing clone upload tests still pass
    Expected Result: Clone endpoint parity is implemented without regressions
    Failure Indicators: New params still ignored/rejected incorrectly, or upload behavior regresses
    Evidence: .sisyphus/evidence/task-8-clone-tests-pass.txt

  Scenario: Invalid clone param values fail predictably
    Tool: Bash (pytest)
    Preconditions: Negative clone tests exist
    Steps:
      1. Run `pytest tests/test_clone.py -v -k "invalid or parameter"`
      2. Confirm bad multipart values return consistent 4xx behavior
    Expected Result: Clone validation matches the defined contract
    Failure Indicators: Invalid values slip through or produce inconsistent errors
    Evidence: .sisyphus/evidence/task-8-clone-invalid-tests.txt
  ```

  **Commit**: NO

- [x] 9. Update README, API examples, and feature labeling for upstream-vs-server clarity

  **What to do**:
  - Update public docs/examples to include the newly exposed generation params and canonical voice-design vocabulary.
  - Clarify which capabilities are native OmniVoice pass-through features versus `omnivoice-server` extensions.
  - Ensure examples for `instructions`, non-verbal symbols, pronunciation control, and advanced generation params are aligned with the implemented contract.

  **Must NOT do**:
  - Do not market server-only features as upstream-native.
  - Do not document unsupported attributes or nonexistent parameters.

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: public documentation correctness and clarity.
  - **Skills**: [`update-docs`, `api-design`]
    - `update-docs`: precise README/example updates.
    - `api-design`: keeps examples aligned with request contract.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: code-focused, not necessary for doc editing.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 10)
  - **Blocks**: Final verification
  - **Blocked By**: 3, 5, 6, 7, 8

  **References**:
  - `README.md` - Main public contract surface.
  - Task 3 inventory artifact - doc surfaces to update.
  - `omnivoice_server/voice_presets.py` and `/v1/voices` behavior - canonical supported metadata.
  - `temp.log` - upstream/native/custom distinctions to preserve.

  **Acceptance Criteria**:
  - [ ] README/examples include the newly supported params and canonical attribute wording.
  - [ ] Server-only features are explicitly labeled as extensions where applicable.
  - [ ] Non-verbal symbols and pronunciation control are documented as pass-through `text` behavior, not as new server-side parsers.

  **QA Scenarios**:
  ```
  Scenario: Public docs reflect implemented request contract
    Tool: Bash (content verification via grep/read-backed checklist)
    Preconditions: Docs updated
    Steps:
      1. Read README sections covering voice design, generation parameters, streaming, and advanced features
      2. Confirm the five new params appear where appropriate
      3. Confirm unsupported attributes and `phoneme_input` are absent
    Expected Result: Public docs match implemented functionality and avoid false claims
    Failure Indicators: Docs omit new params, advertise unsupported attributes, or misrepresent extensions
    Evidence: .sisyphus/evidence/task-9-readme-contract.txt

  Scenario: Extension labeling is explicit
    Tool: Bash (content verification)
    Preconditions: Docs updated
    Steps:
      1. Inspect sections discussing streaming, profile management, batch wrappers, and API surfaces
      2. Confirm wording distinguishes server extension behavior from native upstream OmniVoice capability
    Expected Result: Readers can tell what comes from upstream vs this server wrapper
    Failure Indicators: Ownership of capabilities remains ambiguous
    Evidence: .sisyphus/evidence/task-9-extension-labeling.txt
  ```

  **Commit**: NO

- [x] 10. Perform targeted CLI/config alignment review and minimal direct updates only if required

  **What to do**:
  - Review CLI flags, environment variables, and server settings for any direct exposure gaps caused by the new main-endpoint parameter support.
  - Add minimal settings/CLI updates only if the project intentionally exposes server-level defaults for the newly added parameters.
  - Document explicitly if some new params remain request-only by design.

  **Must NOT do**:
  - Do not launch a broad CLI/config refactor.
  - Do not add server-wide defaults unless they have a clear product reason.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: bounded review with possible small updates.
  - **Skills**: [`python-patterns`, `backend-patterns`]
    - `python-patterns`: config/settings consistency.
    - `backend-patterns`: avoiding contract drift between API and server configuration.
  - **Skills Evaluated but Omitted**:
    - `api-design`: this is primarily an internal surface consistency task.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Task 9)
  - **Blocks**: 11, Final verification
  - **Blocked By**: 5

  **References**:
  - `omnivoice_server/config.py` - Existing server defaults and env var style.
  - CLI/config sections in `README.md` - public exposure of settings.
  - `temp.log` and Task 5 results - determine whether request-only vs server-default exposure is appropriate.

  **Acceptance Criteria**:
  - [ ] Any required CLI/config changes for new params are implemented minimally and documented.
  - [ ] If no direct CLI/config changes are needed, that decision is documented in code/docs/tests where relevant.
  - [ ] No unrelated settings or env var names are changed.

  **QA Scenarios**:
  ```
  Scenario: Config/CLI surface is intentionally aligned
    Tool: Bash (read/config verification)
    Preconditions: Review complete
    Steps:
      1. Inspect `omnivoice_server/config.py` and README configuration sections
      2. Confirm every server-level default exposed is intentional and documented
      3. Confirm no accidental mismatch exists between API behavior and server settings docs
    Expected Result: Config story is coherent and minimal
    Failure Indicators: Docs mention settings that do not exist, or code exposes untracked defaults
    Evidence: .sisyphus/evidence/task-10-config-review.txt

  Scenario: No unrelated config churn was introduced
    Tool: Bash (git diff or targeted file review during execution)
    Preconditions: Any config changes made
    Steps:
      1. Review changed config/README lines
      2. Confirm only directly relevant CLI/env/default lines changed
    Expected Result: Config alignment remains scoped and surgical
    Failure Indicators: Broad unrelated settings edits appear
    Evidence: .sisyphus/evidence/task-10-config-diff-review.txt
  ```

  **Commit**: NO

- [x] 11. Run integration regression sweep across speech, clone, and voices surfaces

  **What to do**:
  - Execute the combined automated regression suite for the touched endpoint surfaces.
  - Add any missing integration assertions needed to prove main speech, clone, preset resolution, instruction validation, and `/v1/voices` metadata work together.
  - Confirm backward compatibility for existing valid requests and example payloads.

  **Must NOT do**:
  - Do not treat individual unit pass results as sufficient if cross-surface regressions remain untested.
  - Do not skip negative/error-path verification.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: integrated verification across multiple endpoint surfaces.
  - **Skills**: [`verification-loop`, `python-testing`]
    - `verification-loop`: disciplined final regression execution.
    - `python-testing`: targeted pytest suite shaping if gaps remain.
  - **Skills Evaluated but Omitted**:
    - `api-design`: verification, not contract design, is primary here.

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential final integration before review wave
  - **Blocks**: Final verification
  - **Blocked By**: 5, 6, 7, 8, 10

  **References**:
  - `tests/test_speech.py`, `tests/test_clone.py`, `tests/test_streaming.py` - primary regression suite.
  - `/v1/voices` tests or newly added coverage - metadata + preset validation.
  - `README.md` examples - use as smoke-test payload references where practical.

  **Acceptance Criteria**:
  - [ ] Combined endpoint regression suite passes.
  - [ ] Existing valid preset and request examples remain functional.
  - [ ] Negative tests for invalid instructions and invalid params pass consistently.
  - [ ] Evidence artifacts capture the integrated verification run.

  **QA Scenarios**:
  ```
  Scenario: Core endpoint regression suite passes end-to-end
    Tool: Bash (pytest)
    Preconditions: All implementation tasks complete
    Steps:
      1. Run `pytest tests/test_speech.py tests/test_clone.py tests/test_streaming.py -v`
      2. Confirm all touched endpoint suites pass
      3. Save full output for review evidence
    Expected Result: Speech, clone, and streaming surfaces pass together
    Failure Indicators: Any regression in touched surfaces
    Evidence: .sisyphus/evidence/task-11-endpoint-regression.txt

  Scenario: Backward-compatible valid requests still succeed
    Tool: Bash (pytest targeted selection)
    Preconditions: Existing example/preset tests remain in suite
    Steps:
      1. Run `pytest tests/test_speech.py -v -k "preset or instructions or response_format"`
      2. Confirm legacy valid request paths still pass after new validation/params
    Expected Result: Existing valid clients remain supported
    Failure Indicators: Formerly valid requests begin failing without deliberate contract change
    Evidence: .sisyphus/evidence/task-11-backward-compat.txt
  ```

  **Commit**: NO

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search changed surfaces for forbidden patterns such as unsupported voice-design attributes or invented pronunciation parameters. Check evidence files exist in `.sisyphus/evidence/`. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `ruff check omnivoice_server/ tests/ && mypy omnivoice_server/ && pytest tests/test_speech.py tests/test_clone.py tests/test_streaming.py -v`. Review changed files for unused imports, dead branches, vague validation errors, duplicated schema drift between speech/clone, and AI-slop patterns.
  Output: `Lint [PASS/FAIL] | Types [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high`
  Execute every task QA scenario, including valid/invalid speech requests, valid/invalid clone multipart requests, `/v1/voices` metadata inspection, and README/docs contract checks. Save artifacts to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  Compare the actual diff against this plan. Verify the implementation exposed only upstream-supported attrs, added only the intended five missing params, preserved pass-through text semantics for non-verbal/pronunciation control, and kept CLI/config changes minimal. Flag any scope creep or unaccounted file changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- Group A (Tasks 1-5): `test(api): cover and expose missing upstream generation params`
- Group B (Tasks 6-8): `feat(voice): validate and canonicalize upstream instruction attributes`
- Group C (Tasks 9-11): `docs(api): align public contract with upstream-supported capabilities`

---

## Success Criteria

### Verification Commands
```bash
pytest tests/test_speech.py tests/test_clone.py tests/test_streaming.py -v
ruff check omnivoice_server/ tests/
mypy omnivoice_server/
```

### Final Checklist
- [ ] All five missing upstream-documented generation params are exposed where intended
- [ ] Invalid `instructions` are rejected with actionable API errors
- [ ] Canonical supported attribute list matches upstream-supported categories only
- [ ] `/v1/audio/speech` and `/v1/audio/speech/clone` remain intentionally aligned
- [ ] README/examples accurately distinguish upstream-native behavior from server extensions
- [ ] No unsupported voice-design attributes or invented pronunciation params are introduced

- [x] 2. Define upstream-compatible instruction validation spec and add failing validation tests

  **What to do**:
  - Extract the canonical supported attribute set and conflict rules from the already-referenced upstream behavior.
  - Decide and codify expected server behavior for duplicates, unsupported attributes, mixed valid/invalid lists, empty instructions, and short-vs-full accent forms.
  - Add failing pytest coverage for the chosen API-layer validation and canonicalization behavior.

  **Must NOT do**:
  - Do not implement helper logic yet.
  - Do not broaden supported attributes beyond upstream-documented categories.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: specification + failing tests scoped to validation behavior.
  - **Skills**: [`python-testing`, `api-design`]
    - `python-testing`: parametrized negative/positive validation tests.
    - `api-design`: clear client-facing 4xx behavior and error payload expectations.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: useful later, but unnecessary for the spec-first test task.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4)
  - **Blocks**: 6, 7, 11
  - **Blocked By**: None

  **References**:
  - `temp.log` - Confirms supported categories and explicitly unsupported attributes.
  - `omnivoice_server/voice_presets.py` - Current server-facing attribute vocabulary and preset mapping.
  - `omnivoice_server/routers/speech.py` - `instructions` precedence path and request entrypoint.
  - `tests/test_speech.py` - Existing tests for instructions precedence and request validation.
  - Upstream reference noted in draft: `OmniVoice/omnivoice/utils/voice_design.py` and `_resolve_instruct()` behavior summary - use as conceptual source for allowlist/conflict logic.

  **Acceptance Criteria**:
  - [ ] Tests cover valid canonical instructions, accepted short accent aliases, duplicate handling, conflicting categories, and unsupported attributes.
  - [ ] Expected HTTP status/error payload shape is explicitly asserted for invalid input.
  - [ ] `pytest tests/test_speech.py -v -k instruction` fails for the new missing validation behavior before implementation.

  **QA Scenarios**:
  ```
  Scenario: Validation spec captures supported and unsupported instructions
    Tool: Bash (pytest)
    Preconditions: New instruction validation tests added
    Steps:
      1. Run `pytest tests/test_speech.py -v -k "instruction or preset"`
      2. Confirm positive cases for canonical upstream-supported attributes are present
      3. Confirm negative cases for unsupported attributes like `cheerful` and conflicting values like `male,female` fail
    Expected Result: New targeted tests fail before implementation and reflect the desired API contract
    Failure Indicators: Missing negative cases, no alias coverage, or unrelated failures dominate
    Evidence: .sisyphus/evidence/task-2-instruction-failing-tests.txt

  Scenario: Accent alias behavior is explicitly locked down
    Tool: Bash (pytest)
    Preconditions: Alias/canonicalization tests exist
    Steps:
      1. Run `pytest tests/test_speech.py -v -k accent`
      2. Confirm short forms such as `british` and canonical forms such as `british accent` are both covered
      3. Confirm expected canonical serialization or downstream behavior is asserted
    Expected Result: Alias acceptance expectations are concretely tested
    Failure Indicators: No alias tests or unclear canonicalization expectation
    Evidence: .sisyphus/evidence/task-2-accent-alias-tests.txt
  ```

  **Commit**: NO

- [x] 3. Inventory public docs and custom-extension labeling gaps

  **What to do**:
  - Audit README, endpoint docs, examples, and any verification/specification docs that mention OmniVoice capabilities.
  - Identify where server-only additions (streaming transport specifics, profile management, REST wrappers) are described in ways that could be confused with native OmniVoice features.
  - Produce a precise checklist of docs/examples/metadata needing updates once implementation lands.

  **Must NOT do**:
  - Do not rewrite docs yet.
  - Do not expand scope into full documentation redesign.

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: documentation inventory and wording clarity.
  - **Skills**: [`update-docs`, `api-design`]
    - `update-docs`: doc-surface inventory and targeted edits.
    - `api-design`: ensures public capability descriptions stay contract-accurate.
  - **Skills Evaluated but Omitted**:
    - `verification-loop`: useful later, but not needed for a docs inventory task.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4)
  - **Blocks**: 7, 9
  - **Blocked By**: None

  **References**:
  - `README.md` - Primary public contract surface already containing voice-design, non-verbal, generation-parameter, and extension claims.
  - `temp.log` - Canonical distinction between upstream-native features and server-only extensions.
  - `omnivoice_server/routers/voices.py` - Client-visible metadata surface informing docs language.
  - Any docs under `docs/` that mention API capabilities or voice features - validate wording consistency.

  **Acceptance Criteria**:
  - [ ] A concrete inventory of all doc/example surfaces needing updates exists.
  - [ ] Every identified server-only extension is marked for explicit labeling.
  - [ ] Every identified upstream capability mention is checked against the supported/canonical attribute set.

  **QA Scenarios**:
  ```
  Scenario: Public capability surfaces are enumerated completely
    Tool: Bash (python or grep-equivalent through project search evidence)
    Preconditions: Inventory completed
    Steps:
      1. Search README and docs for terms such as `stream`, `voice`, `instructions`, `accent`, `OmniVoice`, and `clone`
      2. Cross-check each hit against the inventory checklist
      3. Save the checklist output for later implementation verification
    Expected Result: No major public capability surface is omitted from the checklist
    Failure Indicators: Key files like README or docs/spec pages are absent from the inventory
    Evidence: .sisyphus/evidence/task-3-doc-inventory.txt

  Scenario: Custom-extension labeling gaps are explicit
    Tool: Bash (manual checklist artifact generation)
    Preconditions: Inventory completed
    Steps:
      1. Record each feature that is server-specific rather than upstream-native
      2. Note where wording must change to clarify ownership/source of capability
    Expected Result: Clear doc-update checklist exists before writing implementation docs
    Failure Indicators: Extension-vs-native ownership remains ambiguous
    Evidence: .sisyphus/evidence/task-3-extension-labeling.txt
  ```

  **Commit**: NO

- [x] 4. Define clone endpoint parity contract and add failing multipart tests

  **What to do**:
  - Determine exactly which new generation parameters should be supported on `/v1/audio/speech/clone` based on existing clone semantics and shared inference path.
  - Add failing multipart tests for accepted params, rejected invalid values, and parity with the main speech endpoint where appropriate.
  - Capture explicit exclusions if any main-endpoint parameter should not be clone-supported.

  **Must NOT do**:
  - Do not implement multipart parsing changes yet.
  - Do not assume clone parity without documenting differences.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: bounded parity definition + multipart test scaffolding.
  - **Skills**: [`python-testing`, `backend-patterns`]
    - `python-testing`: multipart endpoint tests and regression patterns.
    - `backend-patterns`: endpoint parity and request-contract rigor.
  - **Skills Evaluated but Omitted**:
    - `api-design`: covered indirectly through endpoint parity, but less necessary than direct testing focus.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3)
  - **Blocks**: 8, 11
  - **Blocked By**: None

  **References**:
  - `omnivoice_server/routers/speech.py` - Clone form parameter definitions and endpoint handling.
  - `omnivoice_server/services/inference.py` - Shared synthesis request mapping that clone ultimately feeds.
  - `tests/test_clone.py` - Existing multipart test style.
  - `temp.log` - Upstream parity target and extension constraints.

  **Acceptance Criteria**:
  - [ ] Failing clone tests define expected support or rejection for each relevant new parameter.
  - [ ] Clone-vs-main differences are explicitly documented in tests/comments.
  - [ ] `pytest tests/test_clone.py -v` fails only for the newly missing clone behavior before implementation.

  **QA Scenarios**:
  ```
  Scenario: Multipart clone parity tests isolate missing behavior
    Tool: Bash (pytest)
    Preconditions: Clone parity tests added
    Steps:
      1. Run `pytest tests/test_clone.py -v`
      2. Inspect failures for new multipart parameter handling cases
      3. Confirm failures are limited to the newly specified clone parity contract
    Expected Result: Clone endpoint parity gap is visible and isolated
    Failure Indicators: No new clone coverage or unrelated endpoint regressions dominate
    Evidence: .sisyphus/evidence/task-4-clone-failing-tests.txt

  Scenario: Clone exclusions are explicit when parity is not exact
    Tool: Bash (pytest / comments audit)
    Preconditions: Tests/spec comments updated
    Steps:
      1. Review test names and comments for each new parameter
      2. Confirm any intentionally unsupported clone parameter is asserted/documented, not silently omitted
    Expected Result: Clone contract is explicit, not implied
    Failure Indicators: Silent omissions or unclear parity behavior
    Evidence: .sisyphus/evidence/task-4-clone-contract.txt
  ```

  **Commit**: NO

- [x] 5. Implement missing generation-parameter support on main speech path

  **What to do**:
  - Extend the main speech request schema with the five missing upstream-documented parameters using validated types/ranges consistent with existing style.
  - Propagate those fields through the internal synthesis request and into `OmniVoiceAdapter.build_kwargs()`.
  - Add minimal config/default wiring only where a server-level default is truly needed; otherwise preserve upstream defaults by passing values only when supplied.
  - Confirm fallback compatibility logic in `build_kwargs()` still behaves correctly if upstream rejects unexpected kwargs.

  **Must NOT do**:
  - Do not alter semantics of existing valid parameters.
  - Do not change unrelated streaming/profile/auth behavior.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: multi-file API/inference implementation with backward-compat considerations.
  - **Skills**: [`python-patterns`, `backend-patterns`]
    - `python-patterns`: maintainable dataclass/schema propagation.
    - `backend-patterns`: request-contract and inference-layer consistency.
  - **Skills Evaluated but Omitted**:
    - `api-design`: useful, but implementation depth matters more here.

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential lead-in to Wave 2
  - **Blocks**: 8, 9, 10, 11
  - **Blocked By**: 1

  **References**:
  - `omnivoice_server/routers/speech.py` - `SpeechRequest` schema and request-to-synthesis construction.
  - `omnivoice_server/services/inference.py` - `SynthesisRequest` and `OmniVoiceAdapter.build_kwargs()` are the core propagation seam.
  - `omnivoice_server/config.py` - Existing defaults pattern for generation params.
  - `tests/test_speech.py` - Must pass the new schema/behavior tests from Task 1.

  **Acceptance Criteria**:
  - [ ] Main endpoint accepts the five missing parameters with validated ranges/types.
  - [ ] New parameters are present in internal request objects and forwarded to model kwargs when supplied.
  - [ ] Existing valid requests without the new params remain unchanged.
  - [ ] `pytest tests/test_speech.py -v` passes for the new parameter cases.

  **QA Scenarios**:
  ```
  Scenario: Main speech endpoint accepts and forwards new upstream params
    Tool: Bash (pytest)
    Preconditions: Implementation complete
    Steps:
      1. Run `pytest tests/test_speech.py -v`
      2. Confirm cases covering `layer_penalty_factor`, `preprocess_prompt`, `postprocess_output`, `audio_chunk_duration`, and `audio_chunk_threshold` now pass
      3. Confirm legacy request tests still pass
    Expected Result: Main speech schema + forwarding behavior is green without regressions
    Failure Indicators: Any new param still rejected, or existing tests regress
    Evidence: .sisyphus/evidence/task-5-speech-tests-pass.txt

  Scenario: Invalid new parameter values fail predictably
    Tool: Bash (pytest)
    Preconditions: Boundary/invalid tests exist
    Steps:
      1. Run `pytest tests/test_speech.py -v -k "layer_penalty_factor or preprocess_prompt or postprocess_output or audio_chunk"`
      2. Confirm invalid type/range requests return expected 4xx behavior
    Expected Result: Invalid new params are rejected at the schema/API layer
    Failure Indicators: Invalid values slip through or produce inconsistent errors
    Evidence: .sisyphus/evidence/task-5-speech-invalid-param-tests.txt
  ```

  **Commit**: NO

- [x] 6. Implement API-layer instruction validation and canonicalization

  **What to do**:
  - Add validation utilities that enforce only upstream-supported instruction categories/values.
  - Support both short accent aliases and canonical full-form accents, but canonicalize internally/output/docs to the full form.
  - Reject unsupported attributes, conflicting categories, and malformed instruction payloads with actionable client-facing errors.
  - Preserve existing precedence order: `instructions` > `speaker` preset > `voice` preset > default prompt.

  **Must NOT do**:
  - Do not accept unsupported emotion/speaking-style attributes.
  - Do not silently ignore invalid `instructions` once validation is implemented.

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: nuanced normalization, conflict detection, and backward-compat API behavior.
  - **Skills**: [`api-design`, `python-patterns`]
    - `api-design`: high-quality 4xx responses and stable client contract.
    - `python-patterns`: clear parsing/normalization helper design.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: helpful but less specific than API contract + Python parsing here.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7)
  - **Blocks**: 9, 11
  - **Blocked By**: 2

  **References**:
  - `omnivoice_server/routers/speech.py` - Existing precedence and request entrypoint.
  - `omnivoice_server/voice_presets.py` - Current supported attributes and preset strings.
  - `temp.log` - Confirmed supported vs unsupported categories.
  - Upstream behavior summary from draft referencing `OmniVoice/omnivoice/utils/voice_design.py` and `_resolve_instruct()` - conceptual source for allowlist/conflict logic.
  - `tests/test_speech.py` - New failing validation tests from Task 2.

  **Acceptance Criteria**:
  - [ ] Supported instructions pass and are canonicalized consistently.
  - [ ] Unsupported attributes return actionable 4xx responses.
  - [ ] Conflicting category values return actionable 4xx responses.
  - [ ] Accent aliases are accepted without loosening the supported allowlist beyond upstream.

  **QA Scenarios**:
  ```
  Scenario: Valid instructions are accepted and canonicalized
    Tool: Bash (pytest)
    Preconditions: Validation implementation complete
    Steps:
      1. Run `pytest tests/test_speech.py -v -k "instruction or accent or preset"`
      2. Confirm valid inputs like `female,british` and `female,british accent` both pass
      3. Confirm canonical output/forwarded instruction behavior matches test expectations
    Expected Result: Supported instruction inputs succeed and normalize consistently
    Failure Indicators: Alias forms fail unexpectedly or canonicalization diverges from the spec
    Evidence: .sisyphus/evidence/task-6-instruction-valid-tests.txt

  Scenario: Unsupported or conflicting instructions fail fast
    Tool: Bash (pytest)
    Preconditions: Negative validation tests exist
    Steps:
      1. Run `pytest tests/test_speech.py -v -k "cheerful or male,female or unsupported"`
      2. Confirm invalid inputs return explicit 4xx responses with actionable messages
    Expected Result: Invalid instructions are rejected before hitting the model
    Failure Indicators: Invalid inputs are silently passed through or error messages are vague
    Evidence: .sisyphus/evidence/task-6-instruction-invalid-tests.txt
  ```

  **Commit**: NO

- [x] 7. Align voice metadata and preset exposure with canonical instruction vocabulary

  **What to do**:
  - Update exposed design attribute metadata so all public surfaces use canonical full-form accent labels and only supported upstream categories.
  - Review preset mapping strings for consistency with the chosen canonical forms.
  - Ensure `/v1/voices` continues to expose accurate design attributes and preset descriptions after validation changes.

  **Must NOT do**:
  - Do not change preset identities.
  - Do not add new presets unrelated to the upstream-alignment goal.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: narrow metadata/preset consistency changes.
  - **Skills**: [`python-patterns`, `api-design`]
    - `python-patterns`: simple catalog updates.
    - `api-design`: public metadata accuracy.
  - **Skills Evaluated but Omitted**:
    - `writing`: docs happen later; this task is code metadata first.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6)
  - **Blocks**: 9, 11
  - **Blocked By**: 2, 3

  **References**:
  - `omnivoice_server/voice_presets.py` - Design attribute catalog and preset mapping.
  - `omnivoice_server/routers/voices.py` - `/v1/voices` response payload.
  - `README.md` voice design section - downstream docs surface to keep consistent.
  - `temp.log` - canonical supported attribute set.

  **Acceptance Criteria**:
  - [ ] `/v1/voices` exposes only supported attribute categories.
  - [ ] Accent values are presented in canonical full-form style.
  - [ ] Preset descriptions remain accurate and compatible with validation logic.

  **QA Scenarios**:
  ```
  Scenario: Voice metadata surface is canonical and accurate
    Tool: Bash (pytest or targeted API call)
    Preconditions: Metadata implementation complete
    Steps:
      1. Exercise `GET /v1/voices` via existing tests or a targeted HTTP call
      2. Confirm `design_attributes` contains only supported categories and canonical accent labels
      3. Confirm preset descriptions remain present and coherent
    Expected Result: Public metadata matches the validated server contract
    Failure Indicators: Unsupported categories appear or accent labels are inconsistent
    Evidence: .sisyphus/evidence/task-7-voices-metadata.txt

  Scenario: Presets still resolve after canonicalization changes
    Tool: Bash (pytest)
    Preconditions: Preset-related tests exist
    Steps:
      1. Run `pytest tests/test_speech.py -v -k preset`
      2. Confirm known presets like `alloy`, `nova`, and `onyx` still resolve correctly
    Expected Result: Preset compatibility is preserved
    Failure Indicators: Existing preset tests regress
    Evidence: .sisyphus/evidence/task-7-preset-compat.txt
  ```

  **Commit**: NO
