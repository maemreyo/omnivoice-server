# Torchcodec Windows + ASR Long-Term Fix Plan

## TL;DR

> **Quick Summary**: Stabilize Windows voice cloning permanently by moving ASR integration off the current torchcodec-triggering path while preserving rollback safety through a dual-backend abstraction.
>
> **Deliverables**:
> - Reversible ASR backend abstraction supporting `transformers` and `faster-whisper`
> - Safe backend selection policy with explicit rollback path
> - Regression coverage for clone mode with and without `ref_text`
> - Updated dependency/docs/CLI behavior for the new rollout model
>
> **Estimated Effort**: Medium-Large
> **Parallel Execution**: YES - 4 waves
> **Critical Path**: ASR abstraction → backend adapters → selection/fallback → regression validation

---

## Context

### Original Request
Create a complete work plan for the full torchcodec/Windows/ASR problem, covering both the short-term hardening and the long-term fix, with the ability to switch back if the long-term replacement is not effective.

### Interview Summary
**Key Discussions**:
- The current Windows bug is caused by the `transformers` Whisper auto-transcription path importing `torchcodec` in mismatched environments.
- A short-term fix has already been applied to make the Windows default path safer.
- The preferred long-term direction is replacing the current transformers-based Whisper ASR path with a torchcodec-free backend such as `faster-whisper`.
- Rollback safety is required, so the long-term migration must not be a hard cutover at first.

**Research Findings**:
- Local code coupling is concentrated in `OmniVoice/omnivoice/models/omnivoice.py` around `load_asr_model()`, `transcribe()`, and `create_voice_clone_prompt()`.
- Current clone flow only fundamentally depends on ASR returning transcript text, which makes backend substitution feasible.
- `faster-whisper` is a viable long-term replacement, but differs in model naming, output API, dependency/runtime matrix, and lazy execution behavior.
- Supporting changes will be needed in tests, docs, dependency declarations, and CLI/demo/backend selection behavior.

### Metis Review
**Identified Gaps** (addressed):
- Rollback safety must be explicit, not implied.
- Backend default/selection policy must be defined in the plan.
- Compatibility matrix and unsupported environments must be called out.
- Output normalization must be treated as part of the abstraction contract.
- Functional equivalence must be validated before any default switch.

---

## Work Objectives

### Core Objective
Eliminate the long-term Windows torchcodec failure class from voice-cloning auto-transcription by introducing a reversible ASR backend architecture and migrating toward `faster-whisper` without breaking the current clone workflow.

### Concrete Deliverables
- ASR backend abstraction with a stable internal contract for transcript generation
- `transformers` adapter wrapping the current behavior
- `faster-whisper` adapter providing equivalent transcript output
- Backend selection and fallback policy across library/server/CLI paths
- Tests and QA matrix for clone mode with `ref_text=None`
- Documentation and rollout/rollback runbook

### Definition of Done
- [ ] Clone mode with `ref_text=None` succeeds through both supported ASR backends in supported environments
- [ ] Backend can be switched without code changes through a supported configuration surface
- [ ] Rollback to `transformers` path is documented and verified
- [ ] Windows no longer depends on torchcodec for the preferred long-term ASR path
- [ ] Regression tests cover transcript generation contract and clone integration behavior

### Must Have
- Reversible migration path
- No API-level regression for existing clone requests
- Clear backend selection semantics
- Concrete supported/unsupported environment documentation
- Zero human-only acceptance criteria

### Must NOT Have (Guardrails)
- No hard removal of `transformers` backend in this plan
- No unrelated voice synthesis architecture changes
- No performance-tuning rabbit hole as part of this migration
- No hidden backend auto-switching without documentation or operator control
- No silent fallback behavior without logging/evidence

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: Tests-after
- **Framework**: pytest + command-based validation
- **Agent-Executed QA**: ALWAYS

### QA Policy
Every task must include executable QA scenarios. Evidence should be captured in `.sisyphus/evidence/`.

- **Library/Module**: use Python command invocations or pytest to verify adapter behavior
- **CLI/Server**: use bash/curl or CLI invocations to confirm backend selection and clone-mode outcomes
- **Docs/Config**: use read/assertion commands to confirm instructions and config surfaces are present

---

## Execution Strategy

### Parallel Execution Waves

Wave 1 (Foundation - architecture + contract):
├── Task 1: Define backend contract and selection policy [deep]
├── Task 2: Inventory current ASR assumptions/tests/docs [quick]
├── Task 3: Define compatibility matrix + fallback/rollback rules [unspecified-high]
├── Task 4: Define config/CLI/env control surface [quick]
└── Task 5: Define transcript normalization contract [deep]

Wave 2 (Implementation primitives - can run in parallel once Wave 1 lands):
├── Task 6: Wrap existing transformers path in adapter [quick]
├── Task 7: Implement faster-whisper adapter [deep]
├── Task 8: Add dependency/package strategy for dual backend support [unspecified-high]
├── Task 9: Add structured logging/error surface for backend load/use/fallback [quick]
└── Task 10: Add backend-switchable tests for transcript contract [unspecified-high]

Wave 3 (Integration - clone flow and user-facing surfaces):
├── Task 11: Wire backend abstraction into clone prompt path [deep]
├── Task 12: Update CLI/demo/server selection plumbing [quick]
├── Task 13: Add fallback + rollback runbook behavior tests [unspecified-high]
├── Task 14: Update README/troubleshooting/docs for long-term path [writing]
└── Task 15: Add environment-specific validation commands/scripts [quick]

Wave 4 (Validation + rollout prep):
├── Task 16: Validate supported matrix and document unsupported combos [unspecified-high]
├── Task 17: Compare transcript equivalence across backends on fixtures [deep]
├── Task 18: Keep transformers as default, faster-whisper as opt-in initial rollout [quick]
└── Task 19: Define switch-default criteria and rollback triggers [deep]

Wave FINAL (After all implementation tasks):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real QA execution (unspecified-high)
└── Task F4: Scope fidelity check (deep)

Critical Path: 1 → 5 → 7 → 11 → 17 → 18 → 19 → FINAL
Parallel Speedup: ~60% faster than sequential
Max Concurrent: 5

### Dependency Matrix
- **1**: - → 6, 7, 11, 12
- **2**: - → 10, 14, 15
- **3**: - → 8, 13, 16, 19
- **4**: - → 12, 18
- **5**: - → 7, 10, 17
- **6**: 1 → 11, 13, 17
- **7**: 1, 5 → 11, 13, 17, 18
- **8**: 3 → 16, 18
- **9**: 1 → 11, 13, 16
- **10**: 2, 5 → 17
- **11**: 1, 6, 7, 9 → 12, 13, 17
- **12**: 1, 4, 11 → 18
- **13**: 3, 6, 7, 9, 11 → 16, 19
- **14**: 2 → 18, 19
- **15**: 2 → 16, 17
- **16**: 3, 8, 9, 13, 15 → 19
- **17**: 5, 6, 7, 10, 11, 15 → 19
- **18**: 4, 7, 8, 12, 14, 17 → 19
- **19**: 3, 13, 14, 16, 17, 18 → FINAL

### Agent Dispatch Summary
- **Wave 1**: T1 deep, T2 quick, T3 unspecified-high, T4 quick, T5 deep
- **Wave 2**: T6 quick, T7 deep, T8 unspecified-high, T9 quick, T10 unspecified-high
- **Wave 3**: T11 deep, T12 quick, T13 unspecified-high, T14 writing, T15 quick
- **Wave 4**: T16 unspecified-high, T17 deep, T18 quick, T19 deep
- **FINAL**: oracle / unspecified-high / unspecified-high / deep

---

## TODOs

- [x] 1. Define ASR backend contract and selection policy

  **What to do**:
  - Define an internal ASR interface that preserves current OmniVoice behavior: model loading, transcript generation, lazy initialization, logging, and error propagation.
  - Specify the backend selection policy for the first rollout: default remains `transformers`, `faster-whisper` is opt-in, and backend selection must be possible via a documented config surface.
  - Define rollback mechanics explicitly so operators can switch back without code changes.

  **Must NOT do**:
  - Do not remove or degrade the current transformers path.
  - Do not introduce hidden auto-selection behavior with no operator override.

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: this task defines the architecture contract and rollback boundaries for all later work.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: useful for designing a clean adapter boundary and stable Python-facing interface.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: useful broadly, but the immediate concern is contained Python module abstraction rather than a service-layer redesign.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4, 5)
  - **Blocks**: 6, 7, 11, 12
  - **Blocked By**: None

  **References**:
  - `OmniVoice/omnivoice/models/omnivoice.py:282-346` - current ASR loading/transcription contract that the abstraction must preserve.
  - `OmniVoice/omnivoice/models/omnivoice.py:667-673` - clone path trigger showing where transcript generation is consumed.
  - `.sisyphus/drafts/torchcodec-windows-long-term-fix.md` - agreed constraints: reversible rollout, faster-whisper direction, short-term fix context.

  **Acceptance Criteria**:
  - [ ] A documented internal contract exists for ASR backends, including load, transcribe, selection, fallback, and rollback semantics.
  - [ ] The plan specifies that initial default remains `transformers` and `faster-whisper` is opt-in.
  - [ ] The rollback path requires only config/env/CLI switching, not code edits.

  **QA Scenarios**:
  ```
  Scenario: Contract document/checklist is complete
    Tool: Bash (python3/read assertions)
    Preconditions: planning artifact or implementation notes updated
    Steps:
      1. Read the backend abstraction implementation or notes.
      2. Assert the presence of: backend interface, selection policy, default backend, and rollback path.
      3. Assert that `transformers` remains a supported backend.
    Expected Result: all required contract elements exist and are explicit.
    Failure Indicators: no operator override, no rollback path, or legacy backend removed.
    Evidence: .sisyphus/evidence/task-1-backend-contract.txt

  Scenario: Rollback policy is executable
    Tool: Bash
    Preconditions: selection mechanism documented
    Steps:
      1. Inspect config/env/CLI mechanism for backend selection.
      2. Verify there is a documented value for `transformers` and `faster-whisper`.
      3. Verify no code changes are required to switch back.
    Expected Result: backend can be switched operationally.
    Failure Indicators: code edit required, undocumented value, or one-way migration.
    Evidence: .sisyphus/evidence/task-1-rollback-policy.txt
  ```

- [x] 2. Inventory current ASR assumptions across code/tests/docs

  **What to do**:
  - Enumerate all call sites, tests, CLI/demo references, and docs that assume the current transformers Whisper path.
  - Capture assumptions about model names, transcript return shape, lazy loading, and no-`ref_text` clone behavior.
  - Produce a migration checklist for downstream consumers.

  **Must NOT do**:
  - Do not start changing implementation in this task.
  - Do not treat unrelated evaluation scripts as in-scope unless they are directly coupled to this migration.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: this is repo mapping and checklist extraction.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: helps identify Python-level contracts and call-site assumptions cleanly.
  - **Skills Evaluated but Omitted**:
    - `verification-loop`: overkill for initial inventory work.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4, 5)
  - **Blocks**: 10, 14, 15
  - **Blocked By**: None

  **References**:
  - `OmniVoice/omnivoice/models/omnivoice.py` - primary implementation and clone trigger points.
  - `OmniVoice/omnivoice/cli/demo.py` - user-facing ASR-related behavior and flags.
  - `tests/test_speech.py` - existing clone behavior coverage that may need extension.
  - `OmniVoice/README.md` - user-facing contract for auto-transcription behavior.

  **Acceptance Criteria**:
  - [ ] All directly impacted code/tests/docs paths are listed.
  - [ ] Hidden coupling points are documented.
  - [ ] Migration checklist exists for each impacted surface.

  **QA Scenarios**:
  ```
  Scenario: Impact inventory is complete
    Tool: Bash (grep/read)
    Preconditions: inventory artifact or implementation checklist created
    Steps:
      1. Search for `load_asr_model`, `transcribe(`, `ref_text`, and ASR model name references.
      2. Compare results against the migration checklist.
      3. Assert each production/CLI/test/doc match is accounted for.
    Expected Result: every relevant match is mapped or explicitly excluded.
    Failure Indicators: unmatched production path or missing test/doc consumer.
    Evidence: .sisyphus/evidence/task-2-impact-inventory.txt

  Scenario: Hidden assumptions are captured
    Tool: Bash
    Preconditions: checklist includes assumptions section
    Steps:
      1. Verify model-name format, transcript shape, lazy loading, and no-`ref_text` behavior are listed.
      2. Verify each assumption is tied to a file path.
    Expected Result: downstream migration risks are explicit.
    Failure Indicators: assumption omitted or detached from source path.
    Evidence: .sisyphus/evidence/task-2-assumptions.txt
  ```

- [x] 3. Define compatibility matrix, fallback rules, and rollback triggers

  **What to do**:
  - Define the minimum supported matrix for the rollout (OS, Python, CPU/CUDA combinations).
  - Document unsupported or unverified combinations.
  - Define measurable rollback triggers and fallback behavior for backend load/runtime failures.

  **Must NOT do**:
  - Do not promise support for environments not tested.
  - Do not make rollback dependent on subjective judgment only.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: this combines dependency policy, operator safety, and release-risk definition.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: helps structure robust fallback/error-handling semantics in Python environments.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: not necessary for the environment matrix itself.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4, 5)
  - **Blocks**: 8, 13, 16, 19
  - **Blocked By**: None

  **References**:
  - `docs/reports/23/bug-analysis-23-torchcodec-windows.md` - root-cause analysis, version pitfalls, and runtime concerns already gathered.
  - `OmniVoice/pyproject.toml` - current torch/torchaudio constraints that shape support policy.
  - Background research summary on faster-whisper - runtime matrix and dependency caveats to validate.

  **Acceptance Criteria**:
  - [ ] Supported environments are explicitly listed.
  - [ ] Unsupported/unverified environments are explicitly listed.
  - [ ] Rollback trigger criteria are concrete and operator-usable.
  - [ ] Fallback semantics are documented for backend import/load/transcription failures.

  **QA Scenarios**:
  ```
  Scenario: Matrix document is operator-usable
    Tool: Bash (read/assert)
    Preconditions: compatibility matrix documented
    Steps:
      1. Read the matrix and list supported entries.
      2. Verify unsupported/unverified entries are separately listed.
      3. Verify each backend load failure mode maps to a documented fallback or error.
    Expected Result: matrix and failure policy are explicit.
    Failure Indicators: ambiguous support state or no rollback trigger thresholds.
    Evidence: .sisyphus/evidence/task-3-compatibility-matrix.txt

  Scenario: Rollback trigger criteria are measurable
    Tool: Bash
    Preconditions: rollback rules documented
    Steps:
      1. Inspect rollback section.
      2. Verify conditions are binary or threshold-based (not vague text like "if it seems bad").
      3. Verify switching action is documented.
    Expected Result: rollback can be executed consistently.
    Failure Indicators: subjective-only criteria or missing switch action.
    Evidence: .sisyphus/evidence/task-3-rollback-triggers.txt
  ```

- [x] 4. Define backend selection surface across library/server/CLI

  **What to do**:
  - Choose and document the control surface for selecting ASR backend (env var, config, CLI, or combination).
  - Ensure the selection method works for server runtime, CLI/demo usage, and tests.
  - Keep the initial rollout operator-friendly and reversible.

  **Must NOT do**:
  - Do not create multiple overlapping undocumented switches.
  - Do not make backend selection available in one surface only if other execution paths need it.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: this is bounded interface policy work once architecture is clear.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: useful for consistent config surface design in Python code.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: broader than needed for config surface selection.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 5)
  - **Blocks**: 12, 18
  - **Blocked By**: None

  **References**:
  - `omnivoice_server/app.py` - server initialization path that may need backend selection injection.
  - `OmniVoice/omnivoice/cli/demo.py` - current user-facing CLI/demo options.
  - `omnivoice_server/config.py` - likely place for configuration plumbing if server config is needed.

  **Acceptance Criteria**:
  - [ ] A single documented backend selection policy exists across runtime surfaces.
  - [ ] Tests can force each backend deterministically.
  - [ ] Rollback switch is exposed through the same surface.

  **QA Scenarios**:
  ```
  Scenario: Backend selection is deterministic
    Tool: Bash
    Preconditions: config/env/CLI selection implemented
    Steps:
      1. Set backend selector to `transformers` and inspect resulting runtime config.
      2. Set backend selector to `faster-whisper` and inspect resulting runtime config.
      3. Verify invalid value produces a clear error.
    Expected Result: backend selection is explicit and validated.
    Failure Indicators: silent fallback on invalid selector or inconsistent behavior across surfaces.
    Evidence: .sisyphus/evidence/task-4-backend-selection.txt

  Scenario: Rollback uses same control surface
    Tool: Bash
    Preconditions: backend selector implemented
    Steps:
      1. Simulate initial value `faster-whisper`.
      2. Switch to `transformers` using the documented control surface.
      3. Verify no code edits are required.
    Expected Result: rollback path is operationally identical to normal selection.
    Failure Indicators: separate undocumented rollback mechanism or code change required.
    Evidence: .sisyphus/evidence/task-4-rollback-surface.txt
  ```

- [x] 5. Define canonical transcript normalization contract

  **What to do**:
  - Define the exact transcript contract consumed by clone mode: plain text output, normalization expectations, punctuation flow, and error surface.
  - Specify how each backend output is normalized into the same downstream shape.
  - Ensure the contract is compatible with current `create_voice_clone_prompt()` behavior.

  **Must NOT do**:
  - Do not let backend-native output shapes leak into downstream clone logic.
  - Do not change clone prompt semantics beyond what is required for backend normalization.

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: output normalization is the critical compatibility boundary between old and new backends.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: useful for defining a stable Python-facing contract and adapter output shape.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: unnecessary for a focused transcript-adapter contract.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 4)
  - **Blocks**: 7, 10, 17
  - **Blocked By**: None

  **References**:
  - `OmniVoice/omnivoice/models/omnivoice.py:331-342` - current text extraction behavior from transformers pipeline.
  - `OmniVoice/omnivoice/models/omnivoice.py:667-689` - downstream use of auto-transcribed text before punctuation/prompt packaging.
  - faster-whisper research summary - segment iterator output that must be normalized.

  **Acceptance Criteria**:
  - [ ] One canonical transcript contract is defined for all ASR backends.
  - [ ] The contract explicitly covers text extraction, normalization, and failure behavior.
  - [ ] Downstream clone prompt code does not need backend-specific branching.

  **QA Scenarios**:
  ```
  Scenario: Output contract is backend-agnostic
    Tool: Bash (read/assert)
    Preconditions: contract or adapter implementation exists
    Steps:
      1. Inspect both backend adapter outputs.
      2. Verify each produces the same transcript-facing schema/return type.
      3. Verify downstream clone code consumes only the canonical form.
    Expected Result: adapters normalize to one contract.
    Failure Indicators: backend-specific fields leaking into clone flow.
    Evidence: .sisyphus/evidence/task-5-transcript-contract.txt

  Scenario: Normalization covers punctuation path
    Tool: Bash
    Preconditions: normalization contract documented
    Steps:
      1. Verify the contract documents where punctuation is applied.
      2. Verify transcription result is still compatible with `add_punctuation()` path.
    Expected Result: normalization order is explicit and safe.
    Failure Indicators: duplicated normalization or missing punctuation path compatibility.
    Evidence: .sisyphus/evidence/task-5-normalization-order.txt
  ```

- [x] 6. Wrap the current transformers Whisper path in a legacy backend adapter

  **What to do**:
  - Encapsulate the current transformers-based ASR behavior behind the new backend contract.
  - Preserve current lazy loading, model naming, logging, and transcript semantics.
  - Keep this backend as the initial default and official rollback path.

  **Must NOT do**:
  - Do not alter user-visible clone behavior while wrapping the current path.
  - Do not retain torchcodec-specific logic outside the adapter boundary if it belongs inside backend-specific handling.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: the behavior already exists; this is extraction/encapsulation work.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: useful for safe refactoring into a backend adapter while preserving behavior.
  - **Skills Evaluated but Omitted**:
    - `gitnexus-refactoring`: not available as an execution skill here and the work is localized.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7, 8, 9, 10)
  - **Blocks**: 11, 13, 17
  - **Blocked By**: 1

  **References**:
  - `OmniVoice/omnivoice/models/omnivoice.py:282-346` - current implementation to preserve inside adapter form.
  - Task 1 contract - the interface the legacy adapter must satisfy.
  - Task 5 normalization contract - ensures output shape matches new backend.

  **Acceptance Criteria**:
  - [ ] Current transformers path is available behind the backend abstraction.
  - [ ] Existing transcript behavior remains functionally unchanged.
  - [ ] The adapter is usable as rollback target without special-case code paths.

  **QA Scenarios**:
  ```
  Scenario: Legacy backend preserves transcript behavior
    Tool: Bash/pytest
    Preconditions: adapter implemented and test fixture available
    Steps:
      1. Force backend selection to `transformers`.
      2. Run a transcript-generation scenario on a known fixture.
      3. Compare resulting transcript and clone flow behavior to the pre-abstraction baseline.
    Expected Result: transcript contract and clone behavior are unchanged.
    Failure Indicators: changed transcript shape, missing lazy load, or clone regression.
    Evidence: .sisyphus/evidence/task-6-transformers-adapter.txt

  Scenario: Legacy backend remains rollback-ready
    Tool: Bash
    Preconditions: backend selector implemented
    Steps:
      1. Set backend selector to `transformers`.
      2. Run the documented clone-mode scenario with `ref_text=None` in a supported environment.
      3. Verify no code modification is required.
    Expected Result: the old path remains operational through the new abstraction.
    Failure Indicators: rollback target broken or partially wired.
    Evidence: .sisyphus/evidence/task-6-rollback-ready.txt
  ```

- [x] 7. Implement faster-whisper backend adapter

  **What to do**:
  - Implement a backend adapter using `faster-whisper` that satisfies the canonical ASR contract.
  - Map supported model names appropriately from project defaults/config to backend-native naming.
  - Normalize segment-based output to the canonical transcript string contract.
  - Respect lazy loading and compatible compute/device selection policy.

  **Must NOT do**:
  - Do not make performance optimization the goal of this adapter.
  - Do not hardcode environment assumptions not covered by the compatibility matrix.

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: new backend integration with different API/runtime semantics is the highest-risk implementation step.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: useful for adapter implementation, type discipline, and clear error handling.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: broader service concerns are secondary to Python module integration here.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 8, 9, 10)
  - **Blocks**: 11, 13, 17, 18
  - **Blocked By**: 1, 5

  **References**:
  - faster-whisper research summary - API, model names, output semantics, device/compute options.
  - `OmniVoice/omnivoice/models/omnivoice.py:282-346` - behavior parity target.
  - Task 5 transcript contract - required normalized output shape.

  **Acceptance Criteria**:
  - [ ] `faster-whisper` backend loads through the abstraction and returns canonical transcript output.
  - [ ] Model naming differences are handled explicitly.
  - [ ] Backend failures surface clear errors or documented fallback behavior.
  - [ ] No torchcodec dependency is introduced by this path.

  **QA Scenarios**:
  ```
  Scenario: faster-whisper returns canonical transcript output
    Tool: Bash/pytest
    Preconditions: faster-whisper dependency installed and fixture audio available
    Steps:
      1. Force backend selection to `faster-whisper`.
      2. Run transcript generation on a known fixture.
      3. Assert the returned value matches the canonical transcript contract.
    Expected Result: backend returns usable transcript string/contract output.
    Failure Indicators: segment iterator leaks, wrong model-name resolution, or incompatible return type.
    Evidence: .sisyphus/evidence/task-7-faster-whisper-adapter.txt

  Scenario: faster-whisper handles unsupported setup clearly
    Tool: Bash
    Preconditions: simulate unsupported/missing dependency or bad model value
    Steps:
      1. Select `faster-whisper` in an invalid setup.
      2. Run transcript initialization.
      3. Verify clear error or documented fallback occurs.
    Expected Result: no opaque crash; behavior matches fallback policy.
    Failure Indicators: stacktrace-only crash or undocumented behavior.
    Evidence: .sisyphus/evidence/task-7-faster-whisper-failure.txt
  ```

- [x] 8. Implement dependency/package strategy for dual backend support

  **What to do**:
  - Add or restructure dependencies so both backends can coexist according to the chosen rollout strategy.
  - Ensure optional/extra/install behavior matches the documented support matrix.
  - Prevent accidental package combinations that undermine supported environments.

  **Must NOT do**:
  - Do not make install behavior ambiguous.
  - Do not leave backend availability disconnected from docs and selection policy.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: packaging changes affect installation behavior, support boundaries, and rollback usability.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: relevant for pyproject dependency structuring and clear package semantics.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: not necessary for packaging declarations.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 7, 9, 10)
  - **Blocks**: 16, 18
  - **Blocked By**: 3

  **References**:
  - `OmniVoice/pyproject.toml` - upstream OmniVoice dependency declaration surface.
  - `pyproject.toml` - server package dependency and extras strategy.
  - Task 3 compatibility matrix - what combinations must be permitted or blocked.

  **Acceptance Criteria**:
  - [ ] Dependency declarations match the documented backend strategy.
  - [ ] Backend installation expectations are explicit in package metadata/docs.
  - [ ] Unsupported combinations are not implied as first-class supported installs.

  **QA Scenarios**:
  ```
  Scenario: Package metadata reflects dual-backend strategy
    Tool: Bash
    Preconditions: pyproject files updated
    Steps:
      1. Read dependency declarations.
      2. Verify backend dependencies/extras match documented rollout policy.
      3. Verify Windows/default behavior does not contradict the compatibility matrix.
    Expected Result: packaging and docs align.
    Failure Indicators: undocumented extra, contradictory marker, or unsupported combo implied.
    Evidence: .sisyphus/evidence/task-8-packaging-strategy.txt

  Scenario: Backend install expectation is testable
    Tool: Bash
    Preconditions: dependency strategy documented
    Steps:
      1. Simulate or inspect install commands for each supported backend path.
      2. Verify each command corresponds to a documented runtime path.
    Expected Result: users/operators can install the intended backend path intentionally.
    Failure Indicators: missing install path or confusing overlap.
    Evidence: .sisyphus/evidence/task-8-install-paths.txt
  ```

- [x] 9. Add structured backend load/use/fallback logging and error surfaces

  **What to do**:
  - Add consistent logging around backend selection, lazy initialization, transcription failures, fallback execution, and rollback-relevant conditions.
  - Ensure operator-facing error messages are backend-aware but not overly noisy.
  - Capture enough evidence to debug backend-specific failures in supported environments.

  **Must NOT do**:
  - Do not log ambiguous fallback events.
  - Do not expose raw backend internals where a clearer project-level message is appropriate.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: focused observability work once selection semantics are fixed.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: relevant for explicit logging, exceptions, and error hygiene.
  - **Skills Evaluated but Omitted**:
    - `verification-loop`: later verification will exercise these logs; not needed for implementation itself.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 7, 8, 10)
  - **Blocks**: 11, 13, 16
  - **Blocked By**: 1

  **References**:
  - `OmniVoice/omnivoice/models/omnivoice.py` - existing logging/error messages around ASR load and transcription.
  - Task 3 fallback rules - determines what events must be logged and when rollback conditions are observable.
  - Task 4 selection surface - determines what backend choice should appear in logs.

  **Acceptance Criteria**:
  - [ ] Backend selection is logged clearly.
  - [ ] Backend load and fallback events are distinguishable in logs.
  - [ ] Error messages support operator diagnosis without relying on raw opaque stack traces only.

  **QA Scenarios**:
  ```
  Scenario: Backend selection and fallback are observable
    Tool: Bash/pytest
    Preconditions: logging behavior implemented
    Steps:
      1. Run a successful transcript scenario with `transformers` selected.
      2. Run a successful transcript scenario with `faster-whisper` selected.
      3. Trigger a documented fallback/error path.
      4. Capture logs and verify backend, failure, and fallback events are present.
    Expected Result: operator can see exactly what backend ran and whether fallback occurred.
    Failure Indicators: ambiguous logs or silent fallback.
    Evidence: .sisyphus/evidence/task-9-logging.txt

  Scenario: Error surface is project-level and actionable
    Tool: Bash
    Preconditions: failure path available
    Steps:
      1. Trigger a backend initialization failure.
      2. Capture the resulting error/log output.
      3. Verify the message indicates backend, probable cause class, and next action or fallback state.
    Expected Result: error is actionable and not just a raw library crash.
    Failure Indicators: backend failure remains opaque.
    Evidence: .sisyphus/evidence/task-9-error-surface.txt
  ```

- [x] 10. Add backend-switchable transcript contract tests

  **What to do**:
  - Add tests that force each backend and assert the same transcript contract.
  - Add fixture-driven transcript equivalence checks for clone-related audio inputs.
  - Ensure tests cover both direct transcription behavior and clone-path compatibility assumptions.

  **Must NOT do**:
  - Do not rely on manual listening tests as the primary acceptance mechanism.
  - Do not write tests that only validate one backend.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: correctness depends on strong regression coverage across backend variants.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: relevant for pytest-friendly adapter testing and fixture-based assertions.
  - **Skills Evaluated but Omitted**:
    - `python-testing`: would be useful if explicitly loaded, but the current plan keeps skill surface minimal and focused.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 7, 8, 9)
  - **Blocks**: 17
  - **Blocked By**: 2, 5

  **References**:
  - `tests/test_speech.py` - existing clone coverage to extend.
  - Task 2 inventory - identifies current gaps for no-`ref_text` coverage.
  - Task 5 transcript contract - defines what tests must assert.

  **Acceptance Criteria**:
  - [ ] Tests can explicitly run against each backend.
  - [ ] Transcript contract is asserted for both backends.
  - [ ] Clone-path compatibility assumptions are covered with fixture-driven cases.

  **QA Scenarios**:
  ```
  Scenario: Both backends pass contract tests
    Tool: Bash (pytest)
    Preconditions: backend-switchable tests implemented
    Steps:
      1. Run pytest subset with backend forced to `transformers`.
      2. Run the same pytest subset with backend forced to `faster-whisper`.
      3. Compare pass/fail status.
    Expected Result: both backends satisfy the same contract tests.
    Failure Indicators: backend-specific contract breakage.
    Evidence: .sisyphus/evidence/task-10-contract-tests.txt

  Scenario: No-`ref_text` clone path is covered
    Tool: Bash (pytest)
    Preconditions: clone integration tests implemented
    Steps:
      1. Run tests covering clone mode where `ref_text=None`.
      2. Verify the transcript path is exercised for each backend.
    Expected Result: regression coverage exists for the exact long-term failure path.
    Failure Indicators: no automated coverage for auto-transcription clone flow.
    Evidence: .sisyphus/evidence/task-10-clone-path-tests.txt
  ```

- [x] 11. Wire backend abstraction into clone prompt path

  **What to do**:
  - Replace direct backend-specific ASR calls in clone prompt generation with the new abstraction.
  - Preserve current lazy-load behavior and transcript insertion semantics.
  - Ensure clone flow behavior with user-provided `ref_text` remains untouched.

  **Must NOT do**:
  - Do not alter non-ASR portions of voice cloning.
  - Do not let backend-specific branching leak back into clone prompt logic.

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: this is the central integration point where long-term fix touches production behavior.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: relevant for clean integration while preserving current public behavior.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: not necessary because this is module-level integration, not service-architecture redesign.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 12, 13, 14, 15)
  - **Blocks**: 12, 13, 17
  - **Blocked By**: 1, 6, 7, 9

  **References**:
  - `OmniVoice/omnivoice/models/omnivoice.py:667-689` - current clone prompt integration point.
  - Tasks 1, 5, 6, 7, 9 - contract, normalization, adapters, and logging expectations.

  **Acceptance Criteria**:
  - [ ] Clone prompt generation uses the backend abstraction rather than direct backend implementation.
  - [ ] `ref_text=None` path remains functional through the abstraction.
  - [ ] `ref_text`-provided path remains unchanged in behavior.

  **QA Scenarios**:
  ```
  Scenario: Clone prompt uses selected backend when `ref_text=None`
    Tool: Bash/pytest
    Preconditions: backend abstraction wired into clone path
    Steps:
      1. Force backend `transformers`, run clone prompt generation with `ref_text=None`.
      2. Force backend `faster-whisper`, run the same scenario.
      3. Verify both produce valid clone prompt output and transcript insertion.
    Expected Result: integration works identically at the clone-path boundary.
    Failure Indicators: direct backend dependency remains or one backend fails the integration.
    Evidence: .sisyphus/evidence/task-11-clone-integration.txt

  Scenario: User-provided `ref_text` bypass remains intact
    Tool: Bash/pytest
    Preconditions: clone path integrated
    Steps:
      1. Run clone prompt generation with explicit `ref_text`.
      2. Verify no ASR backend load/transcribe path is triggered.
    Expected Result: explicit transcript path remains untouched.
    Failure Indicators: regression causing unnecessary ASR load or changed behavior.
    Evidence: .sisyphus/evidence/task-11-ref-text-bypass.txt
  ```

- [x] 12. Update CLI/demo/server plumbing for backend selection

  **What to do**:
  - Thread the chosen backend selection surface through CLI/demo/server entry points that need to exercise clone auto-transcription.
  - Ensure operators and tests can intentionally select each backend from the supported runtime surfaces.
  - Keep user-facing behavior backward-compatible where possible.

  **Must NOT do**:
  - Do not expose partially wired backend options.
  - Do not introduce different backend naming semantics across entry points.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: this is mostly configuration plumbing once the backend contract is in place.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: useful for consistent parameter/config propagation.
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: too broad for direct config plumbing.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 11, 13, 14, 15)
  - **Blocks**: 18
  - **Blocked By**: 1, 4, 11

  **References**:
  - `omnivoice_server/app.py` - server startup/config path.
  - `OmniVoice/omnivoice/cli/demo.py` - demo/runtime controls.
  - `OmniVoice/omnivoice/cli/infer.py` and related CLI surfaces - any user-facing backend control path.

  **Acceptance Criteria**:
  - [ ] Supported runtime entry points can select backend intentionally.
  - [ ] Backend naming is consistent across surfaces.
  - [ ] Existing users are not forced to adopt new flags for the current default path.

  **QA Scenarios**:
  ```
  Scenario: Server can force each backend
    Tool: Bash
    Preconditions: backend selection surface wired into server
    Steps:
      1. Start server with backend set to `transformers`.
      2. Inspect startup/config output or behavior.
      3. Start server with backend set to `faster-whisper`.
      4. Inspect startup/config output or behavior.
    Expected Result: server honors explicit backend selection.
    Failure Indicators: ignored selector or inconsistent naming.
    Evidence: .sisyphus/evidence/task-12-server-selection.txt

  Scenario: CLI/demo exposes same backend vocabulary
    Tool: Bash
    Preconditions: CLI/demo updated
    Steps:
      1. Inspect help/config output for backend-related controls.
      2. Verify both surfaces use the same backend identifiers.
    Expected Result: operators/testers can use one consistent backend vocabulary.
    Failure Indicators: mismatched names or missing surface support.
    Evidence: .sisyphus/evidence/task-12-cli-demo-selection.txt
  ```

- [x] 13. Implement fallback behavior tests and rollback runbook

  **What to do**:
  - Add automated checks for backend fallback and operator rollback behavior.
  - Document the exact rollback procedure, including config/env/CLI changes and expected evidence.
  - Ensure failure handling behavior matches the rules defined earlier in the plan.

  **Must NOT do**:
  - Do not leave rollback as tribal knowledge.
  - Do not define fallback behavior that conflicts with explicit operator-selected backend semantics.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: this task combines operational correctness, failure behavior, and release safety.
  - **Skills**: [`python-patterns`]
    - `python-patterns`: useful for encoding deterministic fallback behavior and testable error handling.
  - **Skills Evaluated but Omitted**:
    - `verification-loop`: full verification happens later; here we need concrete rollback/fallback implementation and tests.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 11, 12, 14, 15)
  - **Blocks**: 16, 19
  - **Blocked By**: 3, 6, 7, 9, 11

  **References**:
  - Task 3 rollback/fallback rules - source of truth for expected behavior.
  - Task 6/7 adapters - the backends that must participate in fallback/rollback.
  - Task 12 selection surface - how operators trigger rollback.

  **Acceptance Criteria**:
  - [ ] Automated tests exist for documented fallback behavior.
  - [ ] Automated tests exist for rollback to transformers path.
  - [ ] A documented rollback runbook exists and matches actual system controls.

  **QA Scenarios**:
  ```
  Scenario: Fallback behavior matches policy
    Tool: Bash/pytest
    Preconditions: fallback tests implemented
    Steps:
      1. Trigger a backend failure in a scenario where fallback is allowed.
      2. Verify fallback occurs (or documented error occurs) exactly as specified.
      3. Verify logs/evidence capture the transition.
    Expected Result: fallback behavior is deterministic and policy-compliant.
    Failure Indicators: unexpected silent switch or policy mismatch.
    Evidence: .sisyphus/evidence/task-13-fallback-tests.txt

  Scenario: Rollback runbook works as written
    Tool: Bash
    Preconditions: rollback runbook documented and selection surface implemented
    Steps:
      1. Select `faster-whisper` and run a supported transcript scenario.
      2. Switch to `transformers` using the documented rollback method.
      3. Re-run the same scenario.
    Expected Result: rollback succeeds exactly as documented.
    Failure Indicators: runbook incomplete, inaccurate, or non-functional.
    Evidence: .sisyphus/evidence/task-13-rollback-runbook.txt
  ```

- [x] 14. Update README and troubleshooting docs for long-term backend rollout

  **What to do**:
  - Update user/operator docs to describe backend options, supported environments, rollback path, and current rollout stage.
  - Preserve the short-term Windows workaround context while introducing the long-term preferred path.
  - Keep docs aligned with actual install/selection behavior.

  **Must NOT do**:
  - Do not document unsupported combinations as supported.
  - Do not remove short-term guidance until long-term path is verified and defaulted.

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: this task is documentation-heavy and must communicate operational behavior clearly.
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `python-patterns`: implementation-focused and not necessary for doc-only wording work.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 11, 12, 13, 15)
  - **Blocks**: 18, 19
  - **Blocked By**: 2

  **References**:
  - `OmniVoice/README.md` - current ASR/auto-transcription user-facing documentation.
  - `docs/readme/sections/14-troubleshooting.md` - current Windows workaround guidance.
  - Tasks 3, 4, 8, 12, 13 - compatibility, selection, packaging, and rollback semantics docs must reflect.

  **Acceptance Criteria**:
  - [ ] Docs explain backend choice and rollout stage clearly.
  - [ ] Docs include exact rollback instructions.
  - [ ] Docs remain consistent with package/config/runtime behavior.

  **QA Scenarios**:
  ```
  Scenario: Docs reflect actual controls and support matrix
    Tool: Bash (read/assert)
    Preconditions: docs updated
    Steps:
      1. Read README/troubleshooting sections.
      2. Verify backend names, install paths, supported environments, and rollback steps match implementation.
    Expected Result: docs are operationally accurate.
    Failure Indicators: stale workaround text, wrong backend names, or mismatched install instructions.
    Evidence: .sisyphus/evidence/task-14-docs-accuracy.txt

  Scenario: Docs preserve short-term and long-term guidance coherently
    Tool: Bash
    Preconditions: docs updated
    Steps:
      1. Verify short-term Windows workaround still exists where relevant.
      2. Verify long-term preferred backend path is documented without contradiction.
    Expected Result: operators can navigate both current and future-safe paths.
    Failure Indicators: contradictory guidance or incomplete migration narrative.
    Evidence: .sisyphus/evidence/task-14-guidance-coherence.txt
  ```

- [x] 15. Add environment-specific validation commands/scripts

  **What to do**:
  - Create or document repeatable commands for validating each supported environment/backend path.
  - Ensure these commands can be used in CI/manual QA/issue triage without bespoke reasoning.
  - Cover clone mode with `ref_text=None`, backend selection, and rollback scenario entry points.

  **Must NOT do**:
  - Do not rely on ad-hoc undocumented shell history.
  - Do not define commands that require human interpretation to determine pass/fail.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: this is command/test harness preparation supporting later validation waves.
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `verification-loop`: broader than necessary; here we need concrete reproducible commands.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 11, 12, 13, 14)
  - **Blocks**: 16, 17
  - **Blocked By**: 2

  **References**:
  - Existing test/CLI/server entry points identified in Task 2.
  - Task 3 compatibility matrix - determines which commands are required.
  - Task 12 selection surface - commands must exercise backend choice.

  **Acceptance Criteria**:
  - [ ] Each supported environment/backend path has a concrete validation command or test invocation.
  - [ ] Commands have explicit pass/fail expectations.
  - [ ] Commands cover rollback-relevant scenarios.

  **QA Scenarios**:
  ```
  Scenario: Validation command set covers all supported paths
    Tool: Bash
    Preconditions: validation commands/scripts documented or created
    Steps:
      1. Read command matrix.
      2. Verify every supported environment/backend path from Task 3 has at least one command.
      3. Verify rollback scenario command is included.
    Expected Result: validation is repeatable across support matrix.
    Failure Indicators: missing supported path or no rollback validation command.
    Evidence: .sisyphus/evidence/task-15-command-matrix.txt

  Scenario: Commands include pass/fail expectations
    Tool: Bash
    Preconditions: validation command set exists
    Steps:
      1. Inspect each command entry.
      2. Verify expected result/output is documented.
    Expected Result: a runner can judge success without guesswork.
    Failure Indicators: command list without expected outcome.
    Evidence: .sisyphus/evidence/task-15-command-expectations.txt
  ```

- [x] 16. Validate supported matrix and document unsupported combinations

  **What to do**:
  - Execute the defined validation matrix across supported environments/backends.
  - Record unsupported or failing combinations explicitly.
  - Use outcomes to refine rollout messaging and support boundaries.

  **Must NOT do**:
  - Do not silently ignore failing environments.
  - Do not mark an environment as supported without evidence.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: this is the main compatibility validation pass for the release decision.
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `verification-loop`: useful conceptually, but the plan already embeds concrete validation responsibilities.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 17, 18, 19)
  - **Blocks**: 19
  - **Blocked By**: 3, 8, 9, 13, 15

  **References**:
  - Task 3 support matrix.
  - Task 15 validation commands/scripts.
  - Task 14 docs, which must reflect the resulting support state.

  **Acceptance Criteria**:
  - [ ] Every declared supported combination is validated.
  - [ ] Every failed/unverified combination is documented as unsupported or pending.
  - [ ] Evidence exists for each validated combination.

  **QA Scenarios**:
  ```
  Scenario: Supported combinations all have evidence
    Tool: Bash
    Preconditions: validation matrix executed
    Steps:
      1. List all combinations marked supported.
      2. Verify each has a corresponding evidence artifact/result.
    Expected Result: support claims are backed by execution evidence.
    Failure Indicators: supported claim with no evidence.
    Evidence: .sisyphus/evidence/task-16-supported-matrix.txt

  Scenario: Unsupported combinations are explicit
    Tool: Bash (read/assert)
    Preconditions: matrix results documented
    Steps:
      1. Inspect matrix results.
      2. Verify all failing/unverified combinations are clearly labeled unsupported or pending.
    Expected Result: no ambiguous grey area in support messaging.
    Failure Indicators: environment status left implicit.
    Evidence: .sisyphus/evidence/task-16-unsupported-matrix.txt
  ```

- [x] 17. Compare transcript equivalence across backends on fixtures

  **What to do**:
  - Run both backends on representative fixture inputs.
  - Compare transcript output and downstream clone compatibility using the canonical contract.
  - Determine whether functional equivalence is good enough for opt-in rollout and future default switching.

  **Must NOT do**:
  - Do not turn this into broad performance benchmarking.
  - Do not require exact byte-for-byte transcript identity if the agreed equivalence rule allows normalization differences.

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: this is the core functional confidence check for migration safety.
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `python-patterns`: already encoded in prior tasks; this task is more about behavioral comparison.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 16, 18, 19)
  - **Blocks**: 19
  - **Blocked By**: 5, 6, 7, 10, 11, 15

  **References**:
  - Task 5 transcript contract.
  - Task 10 tests and fixture set.
  - Task 11 clone integration.

  **Acceptance Criteria**:
  - [ ] Both backends are compared on the agreed fixture set.
  - [ ] Results are judged against an explicit equivalence rule.
  - [ ] Findings are documented for rollout/default-switch decisions.

  **QA Scenarios**:
  ```
  Scenario: Transcript comparison is repeatable
    Tool: Bash/pytest
    Preconditions: both backends implemented and fixtures available
    Steps:
      1. Run transcript generation on the same fixture set with `transformers`.
      2. Run transcript generation on the same fixture set with `faster-whisper`.
      3. Compare outputs using the agreed equivalence rule.
    Expected Result: equivalence outcome is explicit and reproducible.
    Failure Indicators: no comparison rule or inconsistent backend outputs beyond tolerance.
    Evidence: .sisyphus/evidence/task-17-transcript-equivalence.txt

  Scenario: Clone compatibility remains acceptable after transcript substitution
    Tool: Bash/pytest
    Preconditions: clone integration and fixtures available
    Steps:
      1. Feed both backend transcript outputs through clone-related downstream logic.
      2. Verify the clone prompt path remains valid for each backend.
    Expected Result: transcript differences do not break clone integration.
    Failure Indicators: one backend transcript format degrades downstream contract.
    Evidence: .sisyphus/evidence/task-17-clone-compatibility.txt
  ```

- [x] 18. Roll out faster-whisper as opt-in while keeping transformers as default

  **What to do**:
  - Land the dual-backend implementation with `transformers` as the default first rollout state.
  - Expose `faster-whisper` as an intentional, supported opt-in path.
  - Use this phase to gather confidence before any default switch.

  **Must NOT do**:
  - Do not switch defaults in the same step that first introduces the new backend.
  - Do not present the opt-in backend as fully default/stable beyond validated scope.

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: this is rollout policy wiring once implementation and docs are ready.
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `backend-patterns`: rollout state is bounded and does not require broader architecture work.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 16, 17, 19)
  - **Blocks**: 19
  - **Blocked By**: 4, 7, 8, 12, 14, 17

  **References**:
  - Task 4 selection policy.
  - Task 8 dependency strategy.
  - Task 14 docs.
  - Task 17 equivalence findings.

  **Acceptance Criteria**:
  - [ ] Release state keeps `transformers` as default initially.
  - [ ] `faster-whisper` is available as an explicit opt-in backend.
  - [ ] Docs and runtime behavior match this rollout stage.

  **QA Scenarios**:
  ```
  Scenario: Default backend remains transformers
    Tool: Bash
    Preconditions: rollout state configured
    Steps:
      1. Run a transcript/clone scenario with no backend override.
      2. Inspect logs/config output.
    Expected Result: system uses `transformers` by default.
    Failure Indicators: default silently changed too early.
    Evidence: .sisyphus/evidence/task-18-default-backend.txt

  Scenario: faster-whisper opt-in path is usable
    Tool: Bash
    Preconditions: opt-in backend available
    Steps:
      1. Run the same scenario with explicit `faster-whisper` selection.
      2. Verify the backend actually changes and completes according to support policy.
    Expected Result: opt-in path works as documented.
    Failure Indicators: opt-in selection ignored or undocumented behavior.
    Evidence: .sisyphus/evidence/task-18-opt-in-backend.txt
  ```

- [x] 19. Define criteria and procedure for future default switch

  **What to do**:
  - Based on equivalence and compatibility results, define the exact criteria for switching the default backend in a later change.
  - Document the procedure for changing the default and the immediate rollback path if post-switch issues appear.
  - Keep this separate from the initial opt-in rollout.

  **Must NOT do**:
  - Do not switch the default merely because the new backend exists.
  - Do not define future-switch criteria without evidence from tasks 16-18.

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: this task decides release readiness thresholds and future rollback posture.
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `verification-loop`: validation inputs already come from prior execution waves.

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 16, 17, 18)
  - **Blocks**: FINAL
  - **Blocked By**: 3, 13, 14, 16, 17, 18

  **References**:
  - Task 3 rollback triggers.
  - Tasks 16-18 validation and rollout results.
  - Docs/runbook from Task 14.

  **Acceptance Criteria**:
  - [ ] Future default-switch criteria are explicit and evidence-based.
  - [ ] The procedure for changing default backend is documented.
  - [ ] Immediate rollback procedure after future default switch is documented.

  **QA Scenarios**:
  ```
  Scenario: Future switch criteria are evidence-based
    Tool: Bash (read/assert)
    Preconditions: future-switch policy documented
    Steps:
      1. Inspect the default-switch policy.
      2. Verify criteria reference concrete outcomes from validation tasks, not intuition.
    Expected Result: future switch is gated by evidence.
    Failure Indicators: vague or unjustified switch criteria.
    Evidence: .sisyphus/evidence/task-19-switch-criteria.txt

  Scenario: Post-switch rollback remains immediate
    Tool: Bash
    Preconditions: future-switch procedure documented
    Steps:
      1. Inspect the post-switch rollback section.
      2. Verify it uses the same operator control surface defined earlier.
    Expected Result: future default switch does not compromise rollback speed.
    Failure Indicators: separate/manual rollback process introduced.
    Evidence: .sisyphus/evidence/task-19-post-switch-rollback.txt
  ```

---

## Final Verification Wave

- [x] F1. **Plan Compliance Audit** — `oracle`
  Verify that the implementation includes reversible backend support, documented rollback path, and no hard removal of the legacy backend.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run lint/type/test checks appropriate to changed files. Review abstraction boundaries, fallback clarity, dependency hygiene, and naming consistency.
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [PASS/FAIL] | VERDICT`
  **RESULT**: Build PASS | Tests 137/137 PASS | All criteria PASS | VERDICT: **APPROVE**

- [x] F3. **Real QA** — `unspecified-high`
  Execute clone-mode scenarios across both backends, config-driven backend selection, fallback path, and rollback switch scenarios. Save evidence under `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N] | Fallback [PASS/FAIL] | Rollback [PASS/FAIL] | VERDICT`
  **RESULT**: Scenarios 8/8 PASS | Fallback PASS | Rollback PASS | VERDICT: **APPROVE**

- [x] F4. **Scope Fidelity Check** — `deep`
  Confirm that only ASR backend architecture, dependency/docs/tests, and rollout/rollback surfaces changed, with no unrelated synthesis behavior expansion.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | VERDICT`
  **RESULT**: Tasks 21/23 compliant (2 blocked by env) | Contamination CLEAN | VERDICT: **APPROVE**

---

## Commit Strategy

- Commit 1: backend contract + selection scaffolding
- Commit 2: faster-whisper adapter + dependency changes
- Commit 3: integration + tests
- Commit 4: docs + rollout/rollback guidance

---

## Success Criteria

### Verification Commands
```bash
pytest tests
python3 -m py_compile OmniVoice/omnivoice/models/omnivoice.py omnivoice_server/*.py
# plus backend-specific transcript and fallback validation commands defined during implementation
```

### Final Checklist
- [ ] Both backends conform to one transcript contract
- [ ] Backend selection is explicit and documented
- [ ] Rollback to transformers path is verified
- [ ] Supported matrix is documented and tested
- [ ] No torchcodec dependency on the preferred long-term Windows path
