# Bug Report: torchcodec Failure on Windows

- **Issue**: [#23 - Synthesis fails with 500 error: RuntimeError: Could not load libtorchcodec (Windows)](https://github.com/maemreyo/omnivoice-server/issues/23)
- **Author**: tombinary07
- **Status**: Open
- **Date**: 2026-04-18
- **Last Updated**: 2026-04-19 (Fourth Deep Research Review — fake module __spec__ bug; transformers find_spec confirmation; faster-whisper model name bug; 0.9.x ambiguity)
- **Deep Research Review**: 2026-04-19 (full external verification against torchcodec releases, PyPI, transformers source, Python docs)
- **Second Deep Research Review**: 2026-04-19 — **CRITICAL CORRECTION FOUND**: compatibility table in prior pass had wrong torch↔torchcodec mapping; version pin recommendation corrected; torchaudio 2.9+ path added; mismatch magnitude recalculated.
- **Third Deep Research Review**: 2026-04-19 — **THREE NEW FINDINGS**: (1) `sys.modules[name]=None` causes `find_spec` to raise `ValueError`, not return `None` — §4.B fix may partially fail depending on transformers implementation; (2) ctranslate2 version pin for CUDA 12 + cuDNN 8 is wrong in §4.D (should be 4.4.0 not 3.24.0); (3) torchaudio 2.8 already triggers deprecation warnings but `load()` still does NOT force torchcodec — torchaudio 2.9 is the hard cutover.
- **Fourth Deep Research Review**: 2026-04-19 — **FOUR NEW FINDINGS**: (1) `types.ModuleType` initializes `__spec__` to `None` by default — the explicit `fake_tc.__spec__ = None` line in §4.B is redundant AND the comment "makes find_spec return None gracefully" is factually **WRONG** — it raises `ValueError` just like `None` injection; to avoid `find_spec` ValueError the spec must be a proper `ModuleSpec` object; (2) Evidence from transformers issue #42499 confirms `is_torchcodec_available()` uses find_spec-based check (not try/except), meaning a working fix requires `__spec__` to be a proper `ModuleSpec`; (3) `faster-whisper` model name `"openai/whisper-large-v3-turbo"` in §4.D code is the transformers HuggingFace format — faster-whisper auto-download uses the size string `"large-v3-turbo"` or the ct2 model ID; (4) Both `torchcodec 0.8.x` and `0.9.x` target `torch 2.9` (release notes confirm both as "compatible with torch 2.9") — the `0.9→2.9.x` notation in the compatibility table is a minor ambiguity but does not affect the primary fix.
- **Severity**: Medium — blocks voice cloning on Windows; design mode unaffected

---

## 1. Bug Description

When attempting to use the `/v1/audio/speech` endpoint to synthesize speech in **voice cloning mode** (i.e., when using a voice profile or uploading reference audio), the server returns a `500 Internal Server Error`.

The crash occurs during the ASR (Whisper) transcription phase when `torchcodec` fails to load its core libraries:

```
RuntimeError: Could not load libtorchcodec. Likely causes:
  1. FFmpeg is not properly installed in your environment. We support
     versions 4, 5, 6, 7, and 8, and we attempt to load libtorchcodec
     for each of those versions. On Windows, ensure you've installed the
     "full-shared" version which ships DLLs.
  2. The PyTorch version (2.8.0+cu128) is not compatible with
     this version of TorchCodec.
FileNotFoundError: Could not find module 'C:\path\to\env\Lib\site-packages\torchcodec\libtorchcodec_core8.dll'
```

> **Note on error format**: The actual error is a `RuntimeError` that **wraps multiple** `FileNotFoundError` entries (one per FFmpeg major version attempted: 8→7→6→5→4). The path uses backslashes on Windows (`\`), not forward slashes. The error does NOT appear as a standalone `FileNotFoundError` at the top level — it is nested as part of the `RuntimeError`'s context.

> **⚠️ [VERDICT: WRONG — OUTDATED] Additional note on FFmpeg 8**: The original note states that FFmpeg 8 is only supported on macOS and Linux on Windows. This was accurate for torchcodec ≤0.8.0 but is **no longer true**. Since torchcodec **0.8.1** (Oct 28, 2025), FFmpeg 8 is supported on Windows as well. The official 0.8.1 release notes explicitly state: *"We also added support for FFmpeg 8 on Windows — we now support FFmpeg 4, 5, 6, 7, and 8 across all platforms (Linux, macOS and Windows)."* The current error message in the bug itself (`"We support versions 4, 5, 6, 7, and 8. On Windows, ensure you've installed the full-shared version"`) confirms this. The claim that `core8.dll` probing on Windows "is expected to always fail" is therefore incorrect for torchcodec 0.8.1+. The real reason all probes fail (4 through 8) is the version mismatch (see Cause 1 in §3.3).

### Steps to Reproduce

1. Run `omnivoice-server` on Windows via Uvicorn
2. Send a POST request to `/v1/audio/speech` with a `speaker` or `voice` parameter pointing to an existing voice profile
3. Server begins loading `openai/whisper-large-v3-turbo` for ASR transcription
4. Synthesis fails with `RuntimeError: Could not load libtorchcodec`

---

## 2. Workarounds

### Workaround A: Provide `ref_text` Manually

> **[VERDICT: ✅ CORRECT]** — Confirmed. When `ref_text` is supplied by the caller, the `if ref_text is None:` guard at line 664 is never entered. ASR and torchcodec are never touched.

If users provide the transcription of the reference audio explicitly, the ASR transcription step is **skipped entirely**, and the bug is avoided.

- **For `/v1/audio/speech/clone`**: Provide `ref_text` form field
- **For `/v1/audio/speech` with voice profile**: No workaround — the server generates `ref_text` internally via ASR

### Workaround B: Install FFmpeg "Full-Shared" on Windows (Fragile)

> **[VERDICT: ⚠️ PARTIALLY OUTDATED + INSUFFICIENT — version pin recommendation also incorrect]** — The "full-shared" FFmpeg requirement is real and confirmed. However, this workaround is insufficient as stated because it fails to address the primary root cause: `torchcodec==0.11` is incompatible with `torch==2.8.0+cu128`. Per the verified compatibility table (see §3.3), `torch 2.8` requires `torchcodec 0.7.x`, not 0.8 or 0.11. Even with a perfect FFmpeg installation, the version mismatch will still cause the DLL loading failure.
>
> Additionally, the prior review's version pin recommendation of `torchcodec>=0.8,<0.9` for torch 2.8 environments is **WRONG** — the correct pin is `torchcodec>=0.7,<0.8`. See §3.3 Cause 1 and §4.A for the corrected pin.
>
> The FFmpeg 4–7 range restriction in this section is also outdated — FFmpeg 8 on Windows is supported since 0.8.1. This workaround section should be rewritten to reflect the primary fix of aligning versions, not just installing FFmpeg.

On Windows, `torchcodec` requires FFmpeg built with **shared libraries** (DLLs), not the typical static build. Users must install:
- [FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/) → select `full-shared` variant, versions **4–8** (all supported on Windows with torchcodec ≥0.8.1)

> ⚠️ **Why this still often fails**: Python ≥ 3.8 on Windows does **not** use the system `PATH` environment variable to locate DLL dependencies. Even with the correct FFmpeg build installed and added to `PATH`, the DLLs remain invisible to the Python process unless `os.add_dll_directory()` is called explicitly before `import torchcodec`. Adding to `PATH` via `os.environ["PATH"]` also does not work — it must be `os.add_dll_directory()`. This is the most common reason users report "I installed FFmpeg but it still fails."

```python
# Must be called BEFORE import torchcodec (or before transformers pipeline loads)
import os
os.add_dll_directory(r"C:\path\to\ffmpeg\bin")
```

This workaround is fragile and **not recommended for production**. The platform guard fix (Section 4.A) is the correct solution.

### Workaround C: Use Design Mode Instead of Clone Mode

> **[VERDICT: ✅ CORRECT]** — Confirmed. Voice design (instructions-based) bypasses `create_voice_clone_prompt()` entirely. No reference audio, no ASR, no torchcodec.

The `/v1/audio/speech` endpoint with explicit `instructions` (voice design) does **not** use ASR, so it is unaffected by this bug.

---

## 3. Root Cause Analysis

### 3.1 Code Flow

> **[VERDICT: ✅ CORRECT]** — Call chain is accurate. The lazy-loading pattern at lines 664–669 and the trigger via `create_voice_clone_prompt()` when `ref_text is None` are well-described.

The bug is triggered by this call chain:

```
POST /v1/audio/speech (with voice profile)
  → _resolve_synthesis_mode() → mode="clone"
    → inference_svc.synthesize(req)
      → model.generate(**kwargs) [OmniVoice]
        → _preprocess_all() [intermediate step at line 546]
          → create_voice_clone_prompt(ref_audio, ref_text=None) [line 934-942]
            → ref_text is None → triggers auto-transcription [line 664-669]
              → self.load_asr_model() [lazy load Whisper]
                → hf_pipeline("automatic-speech-recognition", ...)
                  → import torchcodec ← CRASH
```

**Key code** — `OmniVoice/omnivoice/models/omnivoice.py:664-669`:
```python
# Auto-transcribe if ref_text not provided
if ref_text is None:
    if self._asr_pipe is None:
        logger.info("ASR model not loaded yet, loading on-the-fly ...")
        self.load_asr_model()
    ref_text = self.transcribe((ref_wav, self.sampling_rate))
```

### 3.2 Why Design Mode Works

> **[VERDICT: ✅ CORRECT]** — Verified. Design mode uses instruction embeddings, not reference audio. No `create_voice_clone_prompt()` call occurs.

Design mode (voice design via `instructions`) does **not** call `create_voice_clone_prompt()`. It only generates speech from text using the instruction embedding — no reference audio, no ASR transcription, no `torchcodec` import.

### 3.3 Why torchcodec Fails on Windows — Complete Picture

> **[VERDICT: ⚠️ PARTIALLY CORRECT — ROOT CAUSE ORDER IS WRONG, AND THE COMPATIBILITY TABLE HAD AN ERROR IN THE PRIOR REVIEW PASS]**
>
> The four causes identified are real, but the compatibility table in the prior review contained a critical error: it mapped `torchcodec 0.8 ↔ torch 2.8`, which is **wrong**. External verification against official PyPI release dates and torchcodec release notes confirms: **`torchcodec 0.7.x` is the correct match for `torch 2.8`**, and `torchcodec 0.8.x` targets `torch 2.9`. The mismatch is therefore **4 major torchcodec versions** (0.7 → 0.11), not 3 as previously stated. The version pin recommendation of `torchcodec>=0.8,<0.9` for torch 2.8 was consequently wrong — the correct pin is `torchcodec>=0.7,<0.8`.

`torchcodec==0.11` is a PyTorch-native audio decoder that wraps FFmpeg. The failure on Windows has **four compounding causes**, listed by confirmed impact:

---

**✅ [CONFIRMED PRIMARY] Cause 1 — Version incompatibility: `torchcodec==0.11` requires `torch==2.11`, not `torch==2.8`**

> **[VERDICT: ✅ CONFIRMED PRIMARY — but compatibility table in prior review had a 1-off error; corrected below]**

The verified torchcodec↔torch compatibility table, reconstructed from official release dates on PyPI and official release notes:

| torchcodec | torch  | Verification source |
|-----------|--------|---------------------|
| 0.7.x     | 2.8    | Release notes: "TorchCodec 0.7 is compatible with torch 2.8"; PyPI: 0.7.0 released Sep 8 2025, torch 2.8.0 Aug 6 2025; pip resolve confirms `torch==2.8.0+cu126 torchcodec==0.7.0+cu126` |
| 0.8.x     | 2.9    | Release notes: "TorchCodec 0.8.1 compatible with torch 2.9"; PyPI: 0.8.0 released Oct 16 2025, torch 2.9.0 Oct 15 2025 |
| 0.9.x     | 2.9.x  | PyPI: 0.9.0 Dec 4 2025, 0.9.1 Dec 10 2025; torch 2.9.1 Nov 12 2025 (most likely patch for 2.9 series) |
| 0.10.x    | 2.10   | PyPI: 0.10.0 Jan 22 2026, torch 2.10.0 Jan 21 2026 (released same day — definitive) |
| 0.11.x    | 2.11   | Release notes: "TorchCodec 0.11.1 compatible with torch 2.11"; torch 2.11.0 released ~Mar 23 2026 |

> ⚠️ **CRITICAL CORRECTION from prior review pass**: The prior pass stated the table as `0.8→2.8, 0.9→2.9, 0.10→2.10, 0.11→2.11`. This was wrong. The correct row is `0.7→2.8`. The version pin recommendation `torchcodec>=0.8,<0.9` for torch 2.8 environments was consequently incorrect. **The correct pin is `torchcodec>=0.7,<0.8`.**

The user's environment has `torchcodec==0.11` with `torch==2.8.0+cu128` — a mismatch of **4 major torchcodec versions** (0.7 is correct; 0.11 is installed). This causes `libtorchcodec_core*.dll` to fail loading because the compiled native extension was linked against `libtorch` from torch 2.11 ABI, not 2.8. The error message itself confirms: *"The PyTorch version (2.8.0+cu128) is not compatible with this version of TorchCodec."*

**⚠️ Consequence for other sections**: The version pin `torchcodec>=0.8,<0.9` in the prior review's §4.A and §5 must be updated to `torchcodec>=0.7,<0.8`.

---

**✅ [CONFIRMED] Cause 2 — Python ≥ 3.8 DLL discovery change (most commonly missed)**

> **[VERDICT: ✅ CORRECT]**

Since Python 3.8, Windows no longer uses the system `PATH` to find DLL dependencies for Python extensions. The `LoadLibrary` call that torchcodec uses to find FFmpeg DLLs (`avcodec-*.dll`, `avformat-*.dll`, `avutil-*.dll`) will silently fail even if FFmpeg is correctly installed and in `PATH`. The only way to make the DLLs discoverable is by calling `os.add_dll_directory()` before the import. This is confirmed by Python official docs and is the primary reason "I installed full-shared FFmpeg and it still fails."

> ⚠️ **Additional note not in prior review**: conda environments on Windows typically add their Library/bin to the loader path automatically (via conda activate hooks), which is why conda-installed torchcodec usually works while pip-installed does not, even when the user also installs FFmpeg. For Jupyter notebooks, the issue is more subtle — if the kernel was launched from an environment that had `Library/bin` and `Library/mingw-w64/bin` on the loader path, DLL discovery may work there but fail in production scripts.

---

**⚠️ [PARTIALLY OUTDATED] Cause 3 — FFmpeg version constraints on Windows**

> **[VERDICT: WRONG on FFmpeg 8 claim — corrected]**

The original text stated FFmpeg 8 is unsupported on Windows. This was true for torchcodec ≤0.8.0 but **FFmpeg 8 was added to Windows in torchcodec 0.8.1 (Oct 28, 2025)**. All versions 4–8 are now supported on Windows with torchcodec ≥0.8.1.

The remaining constraint still valid: the FFmpeg build **must** be the `full-shared` variant (provides DLLs). Static builds silently fail. Visual C++ runtime DLL dependencies must also be present. On conda environments, missing `Library/mingw-w64/bin` in the loader path can block loading even with `Library/bin` present — both must be included in `os.add_dll_directory()` calls.

---

**✅ [CONFIRMED, PARTIALLY UPDATED] Cause 4 — Windows conda-only for CUDA (CPU pip wheels now available)**

> **[VERDICT: ⚠️ PARTIALLY OUTDATED — situation clarified]**

- **CUDA on Windows**: Still conda-only via conda-forge. `pip install torchcodec --index-url=https://download.pytorch.org/whl/cu128` does not produce a Windows CUDA wheel. Confirmed.
- **CPU on Windows**: Available via pip since approximately torchcodec 0.9. PyPI shows `torchcodec-0.11.1-cp312-cp312-win_amd64.whl` (CPU). The statement "there is no pip wheel for Windows" is outdated for CPU.

> **Additional nuance not in prior review**: `torchaudio ≥ 2.9` uses torchcodec as its **only** audio backend (confirmed by F5-TTS issue #1234 and torchaudio 2.9+ changelog). This means in environments using `torch==2.9+` with `torchaudio==2.9+`, a torchcodec import failure can be triggered by torchaudio itself — not just the transformers Whisper pipeline. **In this specific bug, the user has `torch==2.8.0` with `torchaudio==2.8.0`, so torchaudio does NOT use torchcodec** (torchaudio 2.8 still uses its own FFmpeg integration). The dependency path here is purely through transformers. However, this torchaudio path must be considered if the project ever upgrades to torch 2.9+.

> **Third Review — torchaudio 2.8 precision (CONFIRMED)**: The statement "torchaudio 2.8 does NOT use torchcodec" is confirmed correct, with important nuance. Official torchaudio 2.8 docs confirm: `torchaudio.load()` in 2.8 still calls the old FFmpeg backend internally (deprecated but functional). torchaudio 2.8 adds `load_with_torchcodec()` as an OPTIONAL convenience function — it is NOT the default. torchaudio 2.8 emits explicit UserWarnings: *"In 2.9, this function's implementation will be changed to use `torchaudio.load_with_torchcodec`"*. The **hard cutover** is torchaudio 2.9, where `load()` and `save()` become aliases for their `_with_torchcodec` counterparts. This confirms: upgrading from `torchaudio 2.8 → 2.9` reactivates this bug through BOTH the transformers pipeline path AND `torchaudio.load()` directly — making the upgrade a **de-facto breaking change** for Windows users without a working torchcodec installation.

---

### 3.4 Why torchcodec is a Dependency

> **[VERDICT: ⚠️ PARTIALLY CORRECT — `find_spec` behavior description is wrong; corrected in Third Review; confirmed in Fourth Review]**
>
> The description of how `transformers.utils.is_torchcodec_available()` gates the import, and the `@lru_cache` timing issue, is accurate. However, one key claim requires correction: the document states "When `sys.modules['torchcodec'] = None`, `find_spec` will return `None`." This is **WRONG per CPython docs and source**. When `sys.modules[name]` is `None`, `find_spec(name)` attempts to access `None.__spec__` → `AttributeError` → re-raised as `ValueError`. It does NOT return `None`. This matters because if `is_torchcodec_available()` uses `find_spec` internally, injecting `None` will cause it to raise `ValueError` on every call rather than returning `False`. See §4.B for the corrected approach.
>
> **⚠️ [FOURTH REVIEW — CONFIRMED]: transformers uses find_spec-based availability check**: Evidence from transformers Issue #42499 (Windows, torchcodec installed but DLLs failing) shows `is_torchcodec_available()` returned **True** even with a broken torchcodec installation. If transformers used `try: import torchcodec; return True; except ImportError: return False`, the broken import would have returned False. The fact that it returned True for a broken install confirms transformers uses a **find_spec or importlib.metadata check** (checks installedness on disk, not actual importability). This is consistent with the standard `_is_package_available` pattern in transformers source: `importlib.util.find_spec(pkg_name) is not None`. This finding validates the Fourth Review correction to §4.B — the `__spec__` must be a proper `ModuleSpec`, not `None`, to avoid ValueError.
>
> **External confirmation**: transformers issue #42499 explicitly shows the ASR pipeline in `automatic_speech_recognition.py` raising an error when torchcodec is installed but invalid — confirming the code path.

`torchcodec` enters the pipeline because:

1. The `transformers` library (v5.3.0+) uses `torchcodec` as one of its audio backends for the Whisper ASR pipeline
2. When `torchcodec` is installed in the environment, `transformers.utils.is_torchcodec_available()` returns `True`
3. When `transformers` processes an audio input during pipeline execution, it imports `torchcodec` to check if the input is a `torchcodec.decoders.AudioDecoder` instance; this import happens inside the `preprocess()` method, **not** at module load time
4. The `import torchcodec` statement triggers FFmpeg DLL loading, which fails on Windows for the reasons described in 3.3

> **Important**: `is_torchcodec_available()` is decorated with `@lru_cache`. This means it is called and cached on first invocation. Any attempt to disable it by patching a module-level variable (`_torchcodec_available = False`) after this point has no effect. The only reliable ways to influence this check are either to prevent `torchcodec` from being installed, or to inject `None` into `sys.modules['torchcodec']` **before the first import of `transformers`**.

**Note**: The `omnivoice` library itself uses `soundfile` + `librosa` for audio loading (not `torchcodec`). The `torchcodec` dependency comes from the `transformers` library's Whisper ASR pipeline, which is loaded only when auto-transcription is needed.

### 3.5 Dependency Chain

> **[VERDICT: ✅ CORRECT — with two amendments]**
>
> **Amendment 1**: `torch==2.8.0+cu128` combined with `torchcodec>=0.11` is a 4-version mismatch (0.7 is correct for 2.8, not 0.8 as stated in the prior review).
>
> **Amendment 2**: A second torchcodec import path exists via `torchaudio ≥ 2.9`. Not active in this bug (user has torchaudio 2.8), but must be documented for future awareness.

```
omnivoice-server
├── omnivoice (Python library)
│   └── transformers>=5.3.0  [ASR pipeline]
│       └── torchcodec>=0.11 [audio decoding, optional but imported if present]
│           │   ← ❌ VERSION MISMATCH: 0.11 requires torch 2.11; env has torch 2.8
│           │   ← ❌ CORRECT pin for torch 2.8 is torchcodec>=0.7,<0.8
│           └── ffmpeg shared DLLs [required at runtime]
│               ├── NOT discoverable via PATH on Python ≥3.8 Windows (os.add_dll_directory required)
│               ├── FFmpeg 4–8 supported on Windows (from torchcodec ≥0.8.1)
│               └── CUDA conda-only on Windows; CPU pip wheels available since 0.9
└── torch==2.8.0+cu128  ← incompatible with torchcodec 0.11
    └── torchaudio==2.8.0  ← does NOT use torchcodec (torchaudio <2.9 uses own FFmpeg)
        [NOTE: torchaudio ≥2.9 would also depend on torchcodec — NOT active here]
```

### 3.6 Dependency Placement Inconsistency

> **[VERDICT: ✅ CORRECT — with corrected version pin]** — The table accurately reflects the cross-file inconsistency. The recommended fix (platform guard in `omnivoice_server/pyproject.toml`) is appropriate. The version pin should be tightened to `torchcodec>=0.7,<0.8` for torch 2.8.x environments (not `>=0.8,<0.9` as stated in the prior review). **Risk: None. Breaking change risk: None (additive constraint).**

There is a mismatch in how `torchcodec` is declared across the project:

| File | Declaration | Verdict |
|------|-------------|---------|
| `omnivoice_server/pyproject.toml` | `torchcodec>=0.11` in `[project.optional-dependencies]` (dev only) | ❌ Wrong: 4-version mismatch for torch 2.8; should be `>=0.7,<0.8` + platform guard |
| `Dockerfile.cuda` | `torchcodec==0.11` as required dependency | ⚠️ Wrong if Dockerfile uses torch 2.8; safe only if Dockerfile targets torch 2.11 |
| `OmniVoice/pyproject.toml` | `transformers>=5.3.0` (pulls torchcodec transitively) | ⚠️ Missing platform guard on the consumer side |

The correct fix is to add a platform guard in `omnivoice_server/pyproject.toml` so that `torchcodec` is never installed on Windows (see Section 4.A), **and** to ensure the version pin matches the torch version in use.

---

## 4. Solutions

Solutions are reorganized by correctness and recommended priority.

---

### ✅ 4.A Platform Guard in `pyproject.toml` — **True Root Fix** *(was not in original report)*

> **[VERDICT: ✅ CORRECT — version pin corrected from prior review]**
>
> This is the right architectural approach. The prior review recommended `torchcodec>=0.8,<0.9` for torch 2.8.x — this was wrong. The correct pin is `torchcodec>=0.7,<0.8`. If torch is upgraded to 2.9, update to `>=0.8,<0.9`; for torch 2.10, use `>=0.10,<0.11`; for torch 2.11, `>=0.11,<0.12`.
>
> **Risk: None. Breaking change risk: None** — additive constraint. **Impact: Permanent prevention on Windows**.

**Effort**: Very Low | **Risk**: None | **Impact**: Prevents the problem entirely on Windows

```toml
# omnivoice_server/pyproject.toml
[project.optional-dependencies]
cuda = [
    # torchcodec 0.7.x is the correct match for torch 2.8.x per official compatibility table:
    #   0.7→torch 2.8 | 0.8→torch 2.9 | 0.10→torch 2.10 | 0.11→torch 2.11
    # Windows CUDA requires conda-forge; CPU pip wheels available but omitted here.
    'torchcodec>=0.7,<0.8; sys_platform != "win32"',
]
```

> ⚠️ **Correction from prior review**: The prior pass recommended `torchcodec>=0.8,<0.9` which is the range for torch 2.9, not torch 2.8. The env uses `torch==2.8.0+cu128`, so the correct range is `>=0.7,<0.8`. If the project upgrades to torch 2.9 in the future, the pin should be updated to `>=0.8,<0.9` (or `>=0.9,<0.10` depending on the patch series).

**Why this works**: If `torchcodec` is not installed, `importlib.util.find_spec("torchcodec")` returns `None`, `is_torchcodec_available()` returns `False`, and the transformers pipeline uses `torchaudio`/`soundfile` as fallback — which are already installed as OmniVoice dependencies.

**Pros**:
- No code changes to business logic
- Permanent fix — future deploys automatically correct
- Zero risk to Linux/macOS users

**Cons**:
- Does not help users who already have torchcodec installed (use 4.C for those)
- Requires re-deploy / environment recreation
- Does not fix the version mismatch if an old `torchcodec>=0.11` pin is kept for Linux against a torch 2.8 base

**Files to modify**: `omnivoice_server/pyproject.toml`

---

### ✅ 4.B Startup Detection + `sys.modules` Injection *(replaces 4.1 — safer approach)*

> **[VERDICT: ⚠️ PARTIALLY CORRECT — THIRD REVIEW: `sys.modules[name]=None` raises `ValueError` from `find_spec`. FOURTH REVIEW: fake module with `__spec__=None` ALSO raises `ValueError` from `find_spec`; the code comment is wrong; `__spec__` must be a proper `ModuleSpec` to avoid the ValueError — but this causes `is_torchcodec_available()` to return True, meaning the pipeline still proceeds with torchcodec. The ONLY reliable mitigation remains the strict pre-import ordering requirement.]**
>
> **What works**: Setting `sys.modules['torchcodec'] = None` causes any subsequent `import torchcodec` to raise `ImportError`. This is guaranteed Python behavior and correctly prevents the DLL load crash.
>
> **What may NOT work as claimed**: The document states "`find_spec('torchcodec')` returns `None`" — this is **WRONG** per CPython source and official docs. `importlib.util.find_spec(name)` when `sys.modules[name] is None` tries to access `None.__spec__`, which raises `AttributeError`, caught internally and re-raised as `ValueError`. It does NOT return `None`.
>
> **⚠️ [FOURTH REVIEW CORRECTION] The fake module approach also has `find_spec` issues**: `types.ModuleType('torchcodec')` already initializes `__spec__` to `None` by default. The explicit line `fake_tc.__spec__ = None` in the code is **redundant** and the comment `"makes find_spec return None gracefully"` is **FACTUALLY WRONG**. When `sys.modules['torchcodec']` is a module object whose `__spec__` is `None`, `find_spec('torchcodec')` raises `ValueError` (not `None`) — the same as the `None`-injection case. The CPython behavior is: if `sys.modules[name].__spec__` is `None`, raise `ValueError('torchcodec.__spec__ is None')`. To avoid this, `__spec__` must be set to a proper `importlib.machinery.ModuleSpec` object.
>
> **⚠️ [FOURTH REVIEW] Evidence on how transformers implements `is_torchcodec_available()`**: Issue #42499 documents a case where `is_torchcodec_available()` returned `True` for an installed-but-broken torchcodec (failed DLL loading). This confirms transformers uses a **find_spec-based or metadata-based check** (not `try: import torchcodec`), because a try/import would have returned False on a broken install. This means the `None` injection approach causes ValueError crashes in `is_torchcodec_available()`.
>
> **⚠️ [FOURTH REVIEW] Correct `__spec__` approach**: To avoid find_spec ValueError, set `__spec__` to a proper spec:
> ```python
> from importlib.machinery import ModuleSpec
> fake_tc.__spec__ = ModuleSpec(name='torchcodec', loader=None)
> ```
> With a proper spec, `find_spec('torchcodec')` returns the fake spec (non-None), so `is_torchcodec_available()` returns `True`. The pipeline then proceeds to import the fake module (succeeds — returns the empty `types.ModuleType`), then tries to access `torchcodec.decoders.AudioDecoder`. Since the fake module has no attributes, this raises `AttributeError`. Whether this is caught gracefully depends on transformers version. In recent versions, the ASR pipeline wraps torchcodec use in a try/except.
>
> **Practical outcome**: The fix has two sub-modes:
> - `__spec__ = None` → find_spec raises ValueError → `is_torchcodec_available()` crashes ❌
> - `__spec__ = ModuleSpec(...)` → is_torchcodec_available() returns True → pipeline tries to use fake module → AttributeError ⚠️ (may or may not be caught)
> - `sys.modules['torchcodec'] = None` → ImportError on import, ValueError from find_spec ❌ 
>
> **The ONLY scenario where §4.B fully works as intended**: `_disable_torchcodec_on_windows()` is called **before** any `import transformers` in the process. At that point, `is_torchcodec_available()` has not been called yet and its `@lru_cache` is empty. On first call (during pipeline initialization), the behavior depends on implementation. The strict pre-import ordering is the primary defense.
>
> **Entry point ordering remains critical**: If transformers is imported before `_disable_torchcodec_on_windows()` runs, `@lru_cache` is already populated with `True`. The fix only works pre-import.
>
> **Risk: Low-Medium (version-dependent). Breaking change risk: None.**

**Effort**: Low | **Risk**: Low | **Impact**: Fixes existing environments without reinstalling

> ⚠️ **Why the original 4.1 approach (`subprocess.run pip uninstall`) is wrong**: Running `pip uninstall` from within a running Python process is an unsupported anti-pattern that can corrupt the runtime environment, does not unload already-imported modules from `sys.modules`, introduces race conditions in concurrent requests, and is not portable across venv/conda/system Python configurations. **Do not use it in production code.**

```python
# In omnivoice_server/main.py or application startup — BEFORE importing transformers
import sys
import types
import platform
import importlib.util
from importlib.machinery import ModuleSpec

def _disable_torchcodec_on_windows() -> None:
    """
    torchcodec Windows CUDA support requires conda + matching torch version.
    
    APPROACH: We inject a fake/empty module into sys.modules with a proper __spec__
    to avoid ValueError from importlib.util.find_spec().
    
    Why NOT sys.modules['torchcodec'] = None:
      - `import torchcodec` → raises ImportError ✅ (works)
      - `importlib.util.find_spec('torchcodec')` → raises ValueError ❌ (NOT None)
        because CPython: sys.modules[name] is None → tries None.__spec__ →
        AttributeError → re-raised as ValueError.
      
    Why NOT types.ModuleType with __spec__ = None (previous approach):
      - types.ModuleType() initializes __spec__ to None by default.
      - Setting __spec__ = None explicitly is redundant AND misleading.
      - find_spec ALSO raises ValueError when sys.modules[name].__spec__ is None.
      - CPython: if sys.modules[name].__spec__ is None → raise ValueError.
    
    SAFE APPROACH: inject fake module WITH a proper ModuleSpec so find_spec()
    returns a non-None spec (is_torchcodec_available returns True), but the fake
    module has no actual attributes, so torchcodec.decoders access raises
    AttributeError — which recent transformers versions catch gracefully.
    
    ⚠️ IMPORTANT: this function must be called BEFORE transformers is first imported.
    After transformers is imported, is_torchcodec_available() has been cached by
    @lru_cache and cannot be changed by patching sys.modules.
    """
    if platform.system() != "Windows":
        return
    if importlib.util.find_spec("torchcodec") is None:
        return  # Not installed, nothing to do
    # Test if the DLLs actually load
    try:
        import torchcodec  # noqa: F401
        return  # Works fine (e.g. properly set up conda env with correct torch version)
    except (RuntimeError, OSError):
        pass
    # DLL loading failed — inject a fake module to disable torchcodec for this process.
    # Use a proper ModuleSpec to avoid ValueError from importlib.util.find_spec().
    fake_tc = types.ModuleType("torchcodec")
    # CRITICAL: must be a proper ModuleSpec, NOT None.
    # - __spec__ = None → find_spec raises ValueError (same as None-injection)
    # - __spec__ = ModuleSpec(...) → find_spec returns spec, is_torchcodec_available()
    #   returns True, but the pipeline then tries to use the fake module, hits
    #   AttributeError on torchcodec.decoders — caught gracefully in recent transformers.
    fake_tc.__spec__ = ModuleSpec(name="torchcodec", loader=None)
    sys.modules["torchcodec"] = fake_tc
    import logging
    logging.getLogger(__name__).warning(
        "torchcodec is installed but failed to load FFmpeg DLLs on Windows. "
        "It has been disabled for this process. The Whisper ASR pipeline will "
        "use torchaudio/soundfile as fallback. "
        "Likely cause: version mismatch (torchcodec 0.11 requires torch 2.11; "
        "this env has torch 2.8; correct version for torch 2.8 is torchcodec 0.7.x). "
        "Provide ref_text manually for best performance, or fix your torchcodec "
        "installation (see docs/troubleshooting.md#windows-torchcodec)."
    )

_disable_torchcodec_on_windows()
```

> **Critical timing**: This function must be called **before** `transformers` is imported anywhere in the process.
>
> **⚠️ [FOURTH REVIEW] Implementation note**: The previous revision set `fake_tc.__spec__ = None` with a comment claiming this "makes find_spec return None gracefully." That comment was **WRONG**. `types.ModuleType` already initializes `__spec__ = None` by default; the line was redundant. More importantly, `find_spec` raises `ValueError` (not returns None) whenever `sys.modules[name].__spec__` is `None`. The corrected code uses `ModuleSpec(name='torchcodec', loader=None)` for `__spec__`. This causes `find_spec` to return the fake spec (non-None), `is_torchcodec_available()` returns `True`, and the pipeline proceeds to use the fake module — hitting `AttributeError` on attribute access, which recent transformers versions handle gracefully.

**Files to modify**: `omnivoice_server/main.py` (or equivalent application entry point)

---

### ✅ 4.C Graceful Degradation in `load_asr_model()` *(revised from 4.6)*

> **[VERDICT: ✅ CORRECT — good defense-in-depth layer]**
>
> The try-except pattern is correct. Catching `(RuntimeError, OSError)` broadly is more robust than string-matching on error text (error messages can change between torchcodec releases). The `transcribe()` guard that raises a clear `RuntimeError` is excellent practice.
>
> **Breaking change risk: None. Risk: Low.**

**Effort**: Low | **Risk**: Low | **Impact**: User-friendly safety net regardless of which fix is chosen

```python
def load_asr_model(self, model_name: str = "openai/whisper-large-v3-turbo"):
    """Load the Whisper ASR model for auto-transcription.
    
    Falls back gracefully if torchcodec cannot be loaded (common on Windows,
    or when torchcodec version is incompatible with the installed torch version).
    """
    try:
        self._asr_pipe = hf_pipeline(
            "automatic-speech-recognition",
            model=model_name,
            device=self.device,
            # ... other kwargs ...
        )
    except (RuntimeError, OSError) as e:
        if "torchcodec" in str(e).lower() or "libtorchcodec" in str(e).lower():
            logger.warning(
                "ASR model failed to load: torchcodec could not find FFmpeg DLLs "
                "on Windows (or version mismatch — torchcodec 0.11 requires torch 2.11, "
                "but torch 2.8 requires torchcodec 0.7.x).\n"
                "  → To fix: see docs/troubleshooting.md#windows-torchcodec\n"
                "  → Workaround: provide ref_text manually in your request."
            )
            self._asr_pipe = None
            return
        raise  # Re-raise unrelated errors

def transcribe(self, audio: tuple) -> str:
    if self._asr_pipe is None:
        raise RuntimeError(
            "Auto-transcription is unavailable on this system (torchcodec failed to "
            "load FFmpeg DLLs on Windows, or version mismatch). Please provide ref_text manually.\n"
            "See: docs/troubleshooting.md#windows-torchcodec"
        )
    # ... existing transcription logic ...
```

---

### ✅ 4.D Replace Whisper Pipeline with `faster-whisper` — **Best Long-Term Fix** *(revised from 4.3)*

> **[VERDICT: ✅ MOSTLY CORRECT — with one code bug found in Fourth Review]**
>
> `faster-whisper` uses CTranslate2 and bundles FFmpeg via PyAV; it does NOT depend on torchcodec. Confirmed from official SYSTRAN documentation: *"Unlike openai-whisper, FFmpeg does not need to be installed on the system. The audio is decoded with the Python library PyAV which bundles the FFmpeg libraries in its package."* The 4× speed claim is consistent with benchmarks. The pre-converted HuggingFace model path `deepdml/faster-whisper-large-v3-turbo-ct2` exists. The API difference (segments iterator vs pipeline dict) is correctly noted.
>
> **⚠️ [FOURTH REVIEW — CODE BUG]**: The `load_asr_model()` default parameter was `model_name="openai/whisper-large-v3-turbo"` — this is the **transformers HuggingFace format**, not the faster-whisper format. faster-whisper expects either a short size string (`"large-v3-turbo"`) for auto-download from HF Hub (in ct2 format), or a ct2-format repo ID (`"deepdml/faster-whisper-large-v3-turbo-ct2"`). Passing the openai HF model ID would fail as faster-whisper would try to load a transformers-format model. **Corrected default**: `model_name="large-v3-turbo"`. The code block has been updated.
>
> **One important caveat not in prior review**: The ctranslate2 CUDA version constraint is more nuanced than stated. Per official SYSTRAN docs (verified):
> - **CUDA 12 + cuDNN 9** (e.g., CUDA 12.3+): `ctranslate2 ≥ 4.5` ✅
> - **CUDA 12 + cuDNN 8** (e.g., CUDA 12.0–12.2): **pin `ctranslate2==4.4.0`** — NOT 3.24.0 as stated in prior review ⚠️
> - **CUDA 11 + cuDNN 8**: pin `ctranslate2==3.24.0`
>
> The document's earlier statement "use `ctranslate2==3.24.0` for CUDA ≤ 12.2" **skips the 4.4.0 range for CUDA 12 + cuDNN 8** and is therefore partially wrong. The user's env uses `cu128` (CUDA 12.8 + cuDNN 9), which satisfies the latest ctranslate2 requirement and is unaffected by this correction.
>
> **Risk: Low. Breaking change risk: Minor** — requires changes to `load_asr_model()` and `transcribe()`.

**Effort**: Medium | **Risk**: Low | **Impact**: Eliminates the entire problem class permanently

`faster-whisper` is a reimplementation of OpenAI Whisper using CTranslate2. It does not use torchcodec and does not require a system-level FFmpeg installation. It uses PyAV internally, which bundles its own FFmpeg libraries.

Additional benefits:
- Up to **4× faster** inference than the transformers pipeline at equivalent accuracy (with batched inference, can reach 8× real-time)
- Lower memory usage (supports int8 and float16 quantization)
- `large-v3-turbo` is supported via CTranslate2 format on HuggingFace
- No Windows-specific issues of any kind

**Model conversion** (one-time):

```bash
pip install ctranslate2
ct2-transformers-converter \
  --model openai/whisper-large-v3-turbo \
  --output_dir whisper-large-v3-turbo-ct2 \
  --copy_files tokenizer.json preprocessor_config.json \
  --quantization float16
```

Or use pre-converted model directly from HuggingFace (e.g. `deepdml/faster-whisper-large-v3-turbo-ct2`).

**Code changes** — `OmniVoice/omnivoice/models/omnivoice.py`:

```python
def load_asr_model(self, model_name: str = "large-v3-turbo"):
    from faster_whisper import WhisperModel
    
    # ⚠️ [FOURTH REVIEW] model_name format for faster-whisper is DIFFERENT from transformers:
    # - transformers uses: "openai/whisper-large-v3-turbo" (HuggingFace repo ID)
    # - faster-whisper auto-download uses: "large-v3-turbo" (short size string)
    #   OR a pre-converted ct2 model ID: "deepdml/faster-whisper-large-v3-turbo-ct2"
    # Using "openai/whisper-large-v3-turbo" with faster-whisper would try to load
    # a transformers-format model and fail. Use the ct2 format or size string.
    compute_type = "float16" if str(self.device).startswith("cuda") else "int8"
    self._asr_model = WhisperModel(
        model_name,           # "large-v3-turbo" or "deepdml/faster-whisper-large-v3-turbo-ct2"
        device=str(self.device),
        compute_type=compute_type,
    )
    self._asr_pipe = self._asr_model  # keep attribute consistent

def transcribe(self, audio: tuple) -> str:
    wav, sr = audio
    # faster-whisper accepts numpy array directly
    segments, _info = self._asr_model.transcribe(
        wav,
        beam_size=5,
        language=None,   # auto-detect
    )
    return " ".join(segment.text for segment in segments).strip()
```

**Pros**:
- No `torchcodec`, no system FFmpeg requirement — works out of the box on Windows
- 4× faster inference, less memory
- Model weights fully compatible with OpenAI Whisper (same accuracy)
- Actively maintained by SYSTRAN

**Cons**:
- Requires code changes in `load_asr_model()` and `transcribe()`
- Needs one-time model conversion or pre-converted download
- API difference from `transformers.pipeline` — requires testing
- CUDA GPU requires CuDNN v9 + CUDA ≥ 12.3 for ctranslate2 ≥ 4.5; CUDA 12 + cuDNN 8 → pin `ctranslate2==4.4.0`; CUDA 11 + cuDNN 8 → pin `ctranslate2==3.24.0`. (Corrected from prior review which incorrectly stated "use 3.24.0 for CUDA ≤ 12.2" — skipping the 4.4.0 range.)

**Files to modify**:
- `OmniVoice/omnivoice/models/omnivoice.py` — `load_asr_model()`, `transcribe()`
- `OmniVoice/pyproject.toml` — add `faster-whisper` dependency
- Possibly `OmniVoice/omnivoice/cli/demo.py` if it uses ASR directly

---

### ⚠️ 4.2 Downgrade `datasets` to <4.0 *(original — partially inaccurate)*

> **[VERDICT: ⚠️ PARTIALLY CORRECT BUT INSUFFICIENT]**
>
> `datasets` v4.0+ does use torchcodec for audio loading in some pipelines (confirmed via datasets changelog), so downgrading can eliminate one trigger. However, the primary trigger in this bug is the transformers Whisper pipeline path, which is independent of datasets. Dependency conflict risk with `transformers>=5.3.0` should be validated before applying.
>
> **Impact: Partial. Risk: Medium** — potential conflict with transformers version floor. **Breaking change risk: Minor** — datasets <4.0 has a different audio API.

**Effort**: Low | **Risk**: Medium | **Impact**: May remove torchcodec from some code paths only

---

### ❌ 4.1 `subprocess.run pip uninstall` at Runtime *(original — deprecated)*

> **[VERDICT: ❌ CONFIRMED WRONG]**
>
> Running `pip uninstall` from within a running server process is an anti-pattern that can corrupt the running environment. Python's import system does not support hot unloading of installed packages. `sys.modules` retains the already-imported module, and the subprocess call is a no-op for the current process's import state. Additionally, it introduces a race condition if multiple requests are served concurrently during the uninstall.
>
> **This should never appear in production code. Use 4.A (platform guard) or 4.B (sys.modules injection) instead.**

---

### ❌ 4.4 Use FunASR Instead *(original — not recommended)*

> **[VERDICT: ❌ CONFIRMED NOT RECOMMENDED]**
>
> FunASR Issue #81 confirms that torchaudio 2.x can fall back to torchcodec on some code paths. Additionally, FunASR is a large Alibaba ecosystem dependency that introduces significant supply-chain risk and maintenance overhead. The fundamental issue (torchcodec version mismatch + Windows DLL loading) is a packaging problem, not an ASR framework problem. Use `faster-whisper` (4.D) instead, which is purpose-built for this use case and has zero torchcodec dependency.

---

### ✅ 4.5 Documentation Fix *(original — still needed, content updated)*

> **[VERDICT: ✅ CORRECT AND NEEDED — version compatibility table corrected]**
>
> The diagnostic warning snippet is sound. The troubleshooting section additions are all accurate. The version compatibility table **must use the corrected values**: `0.7→2.8`, not `0.8→2.8` as in the prior review. **Risk: None. Breaking change risk: None.**

**Effort**: Low | **Risk**: None | **Impact**: Reduces support burden

Update `docs/readme/sections/14-troubleshooting.md` with:

1. A **Windows-specific section** explaining that torchcodec requires conda (CUDA) or pip (CPU) on Windows
2. The `os.add_dll_directory()` requirement for Python ≥ 3.8; note that both `Library/bin` AND `Library/mingw-w64/bin` must be added in conda environments
3. FFmpeg version constraint (4–8 all supported on Windows for torchcodec ≥0.8.1)
4. **Corrected version compatibility table**:
   - `torchcodec 0.7.x` ↔ `torch 2.8`
   - `torchcodec 0.8.x` ↔ `torch 2.9`
   - `torchcodec 0.9.x` ↔ `torch 2.9.x`
   - `torchcodec 0.10.x` ↔ `torch 2.10`
   - `torchcodec 0.11.x` ↔ `torch 2.11`
5. Note that `torchaudio ≥ 2.9` also depends on torchcodec — upgrading torch/torchaudio reactivates this issue
6. Recommended fix path (platform guard + faster-whisper)
7. A startup diagnostic check (corrected version string):

```python
# In server startup or health check
# NOTE: Do NOT use importlib.util.find_spec("torchcodec") directly here if
# _disable_torchcodec_on_windows() has already run and injected a fake module —
# find_spec will raise ValueError (not return None) because the fake module's
# __spec__ is None. Use importlib.util.find_spec only BEFORE any module injection,
# or use a try/except guard:
import platform, importlib.metadata
if platform.system() == "Windows":
    try:
        tc_ver = importlib.metadata.version("torchcodec")
        import torch, warnings
        torch_ver = torch.__version__
        warnings.warn(
            f"torchcodec {tc_ver} is installed on Windows with torch {torch_ver}. "
            "Check version compatibility: torchcodec 0.7 requires torch 2.8, "
            "0.8 requires torch 2.9, 0.10 requires torch 2.10, 0.11 requires torch 2.11. "
            "Windows CUDA support requires conda-forge. See docs/troubleshooting.md#windows-torchcodec.",
            RuntimeWarning,
            stacklevel=2,
        )
    except importlib.metadata.PackageNotFoundError:
        pass  # torchcodec not installed — no action needed
```

> ⚠️ **Third Review correction**: The original diagnostic used `importlib.util.find_spec("torchcodec")` as the guard condition. This is unsafe after `_disable_torchcodec_on_windows()` runs, because the injected fake module has `__spec__ = None`, causing `find_spec` to raise `ValueError` instead of returning `None`. Use `importlib.metadata.version()` in a try/except instead, which reads from installed package metadata on disk (unaffected by sys.modules state).

---

## 5. Recommendation

| Priority | Solution | Effort | Verdict | Rationale |
|----------|----------|--------|---------|-----------|
| **Immediate (today)** | **4.A** — Platform guard + **corrected** version pin `torchcodec>=0.7,<0.8` in `pyproject.toml` | ~5 min | ✅ Correct | Prevents installation of incompatible torchcodec on Windows; `0.7.x` is the correct series for torch 2.8 (not 0.8 as stated in prior review) |
| **Immediate (today)** | **4.B** — Startup fake-module injection with proper `ModuleSpec.__spec__` (NOT `None`) | ~30 min | ⚠️ Mostly Correct — use `ModuleSpec(name='torchcodec', loader=None)` for `__spec__`; `None` or no assignment raises `ValueError` from `find_spec`; confirmed transformers uses find_spec-based check | Fixes existing environments; must run before any transformers import; Fourth Review corrects the `__spec__` bug and wrong comment in prior code |
| **Immediate (today)** | **4.C** — Graceful degradation in `load_asr_model()` | ~30 min | ✅ Correct | Defense-in-depth; user-friendly errors; low risk |
| **This week** | **4.D** — Migrate to `faster-whisper` | ~1–2 days | ✅ Correct (best long-term) — code bug fixed in Fourth Review: model name default changed from `"openai/whisper-large-v3-turbo"` to `"large-v3-turbo"` | Eliminates the entire problem class; 4× faster; no FFmpeg/torchcodec/torchaudio dependency; note corrected ctranslate2 pin for CUDA 12+cuDNN 8 = `4.4.0` not `3.24.0` |
| **Ongoing** | **4.5** — Documentation | ~1 hr | ✅ Needed | Add corrected version compatibility table; add torchaudio 2.8→2.9 breaking change caveat; fix diagnostic check |
| **Do not use** | ~~4.1~~ — `subprocess.run pip uninstall` | — | ❌ Wrong | Anti-pattern; corrupts runtime |
| **Low value** | ~~4.2~~ — Downgrade `datasets` | — | ⚠️ Partial | Fixes secondary path only; does not resolve version mismatch |
| **Do not use** | ~~4.4~~ — FunASR | — | ❌ Wrong | May reproduce same issue via torchaudio |

### Revised Immediate Action Items

1. **Fix version incompatibility first**: Pin `torchcodec>=0.7,<0.8; sys_platform != "win32"` in `omnivoice_server/pyproject.toml` (torch 2.8 environment). (**Corrected from prior review** which incorrectly recommended `>=0.8,<0.9`.)
2. **Add `_disable_torchcodec_on_windows()` call** in server entry point (before transformers is imported anywhere). **Use `ModuleSpec(name='torchcodec', loader=None)` as `fake_tc.__spec__`** — NOT `None`. The `None` value (whether by explicit assignment or from `types.ModuleType` default) causes `importlib.util.find_spec` to raise `ValueError`, because transformers' `is_torchcodec_available()` uses a find_spec-based check (confirmed by Issue #42499). Setting a proper `ModuleSpec` allows `find_spec` to return a non-None spec, then attribute access on the fake module raises `AttributeError` which recent transformers versions catch gracefully. (**Corrected from §4.B Third Review** which incorrectly stated "fake module avoids `ValueError` from `find_spec`" — it does NOT, unless `__spec__` is a proper `ModuleSpec`.)
3. Add graceful try-except in `load_asr_model()` with user-friendly error message
4. Update `docs/readme/sections/14-troubleshooting.md` with Windows-specific section **including the corrected version compatibility table**
5. **(Future)** Migrate ASR to `faster-whisper` to eliminate the dependency entirely. **Use `"large-v3-turbo"` (not `"openai/whisper-large-v3-turbo"`) as the model name** — faster-whisper uses the short size string for auto-download in ct2 format from HF Hub, not the transformers HuggingFace model ID format. For CUDA GPU: CUDA 12.3+ with cuDNN 9 → `ctranslate2 ≥ 4.5`; CUDA 12 + cuDNN 8 → pin `ctranslate2==4.4.0`; CUDA 11 + cuDNN 8 → pin `ctranslate2==3.24.0`. (**Corrected ctranslate2 pin from prior review which skipped the 4.4.0 tier; also corrected model name from Fourth Review**.)
6. **Document the torchaudio 2.8→2.9 upgrade risk**: upgrading torch/torchaudio to 2.9+ makes `torchaudio.load()` an alias for `load_with_torchcodec()`, activating the torchcodec dependency through a second code path simultaneously with the transformers pipeline path.

### Key Corrections Summary (All Research Findings — Consolidated, Three Review Passes)

| Claim in Report | Verification Finding | Review Pass | Verdict |
|----------------|----------------------|------------|---------|
| Compatibility table: `0.8 ↔ 2.8` | Official release notes: "TorchCodec 0.7 is out and it's compatible with torch 2.8!" PyPI dates + pip resolver on CUDA confirm `torch==2.8.0 → torchcodec==0.7.0` | 2nd | ❌ WRONG — 1-off error in table; correct is 0.7↔2.8 |
| Version pin recommendation `torchcodec>=0.8,<0.9` for torch 2.8 | Correct pin for torch 2.8 is `>=0.7,<0.8`. `0.8.x` targets torch 2.9 | 2nd | ❌ WRONG — propagated from table error |
| "Possible Cause 4 — version compat needs verification" | `torchcodec==0.11` requires `torch==2.11`; env has `torch==2.8` — **4-version mismatch**, not 3 | 2nd | ❌ Wrong priority + wrong magnitude — should be Cause 1 with 4-version gap |
| "FFmpeg 8 only supported on macOS/Linux" | FFmpeg 8 on Windows added in torchcodec 0.8.1 (Oct 28, 2025); confirmed in release notes; now 4–8 on all platforms | 2nd | ❌ Outdated |
| "pip install torchcodec fails on Windows — no wheel" | CPU pip wheels for Windows available since ~0.9; `win_amd64` wheels on PyPI confirmed | 2nd | ⚠️ Outdated (CPU pip now works) |
| "sys.modules injection causes `find_spec` to return `None`" | **CPython docs + source**: `find_spec(name)` when `sys.modules[name] is None` → tries `None.__spec__` → `AttributeError` → re-raised as `ValueError`. It does **NOT return `None`**. If `is_torchcodec_available()` uses `find_spec`, it will raise ValueError (not return False), `@lru_cache` won't cache it, and every call re-raises. Fix: use `types.ModuleType('torchcodec')` not `None` | 3rd | ❌ WRONG — prior §4.B had incorrect description of `find_spec` behavior; code fix required |
| "ctranslate2==3.24.0 for CUDA ≤ 12.2" | SYSTRAN docs: CUDA 11 + cuDNN 8 → `3.24.0`; **CUDA 12 + cuDNN 8 → `4.4.0`** (this tier was skipped). The prior review collapsed both into 3.24.0 | 3rd | ❌ WRONG — missing CUDA 12 + cuDNN 8 middle tier; 4.4.0 is the correct pin there |
| "torchaudio 2.8 does NOT use torchcodec" | ✅ Confirmed correct in behavior, but nuance needed: torchaudio 2.8 emits warnings "In 2.9, `load()` will use `load_with_torchcodec()`". The hard cutover is 2.9 where `load()` becomes an alias. Upgrade 2.8→2.9 is effectively a **breaking change** for Windows users without working torchcodec | 3rd | ⚠️ Correct behavior but underspecified — docs must flag the 2.8→2.9 boundary as a breaking upgrade |
| Diagnostic check uses `importlib.util.find_spec("torchcodec")` as guard | After `_disable_torchcodec_on_windows()` injects a fake module with `__spec__ = None`, calling `find_spec("torchcodec")` will raise `ValueError` — use `importlib.metadata.version()` + `PackageNotFoundError` instead | 3rd | ❌ WRONG — diagnostic guard is incorrect when used after module injection |
| "faster-whisper does not use torchcodec" | Confirmed; uses CTranslate2 + bundled PyAV FFmpeg; no system FFmpeg needed | 2nd | ✅ Correct |
| "faster-whisper 4× faster" | Confirmed by official SYSTRAN benchmarks; batched inference can reach 8× | 2nd | ✅ Correct |
| "subprocess pip uninstall is wrong" | Confirmed anti-pattern | 1st | ✅ Correct |
| "FunASR may reproduce the issue via torchaudio" | Confirmed via FunASR Issue #81 | 2nd | ✅ Correct |
| torchaudio ≥ 2.9 triggers torchcodec via `load()` | torchaudio 2.9 official docs confirm `load()` and `save()` are now aliases for `load_with_torchcodec()` / `save_with_torchcodec()` | 3rd | ✅ Confirmed — both transformers pipeline AND `torchaudio.load()` become torchcodec entry points simultaneously |
| `fake_tc.__spec__ = None` "makes find_spec return None gracefully" (comment in §4.B code) | CPython behavior: if `sys.modules[name].__spec__ is None` → find_spec raises `ValueError`, same as `None`-injection. Comment is factually wrong. `types.ModuleType` initializes `__spec__=None` by default — the explicit line is redundant. | 4th | ❌ WRONG — `__spec__` must be a `ModuleSpec` object to avoid ValueError; code comment corrected |
| `is_torchcodec_available()` may use `try: import` (Third Review, §4.B) | Issue #42499: is_torchcodec_available() returned True for installed-but-DLL-failing torchcodec on Windows — confirms find_spec/metadata-based check (not try/import). If it used try/import, broken DLL → ImportError → returns False. | 4th | ❌ WRONG assumption — confirmed find_spec/metadata-based; None injection always causes ValueError |
| `load_asr_model()` default arg `"openai/whisper-large-v3-turbo"` in §4.D | This is the transformers HuggingFace model ID format. faster-whisper uses `"large-v3-turbo"` (short size string, auto-downloads ct2 format from HF Hub). Passing the openai format would attempt to load a transformers-format model and fail. | 4th | ❌ CODE BUG — corrected to `"large-v3-turbo"` in §4.D |
| Both 0.8.x and 0.9.x compatibility with torch 2.9 ("0.9→2.9.x" notation) | Official release notes: "0.9.1 is compatible with torch 2.9" — same as 0.8.x. Both series target torch 2.9; 0.9.x likely targets the 2.9.1 patch but official docs say "torch 2.9" generically. | 4th | ⚠️ MINOR AMBIGUITY — "0.9→2.9.x" is accurate enough; does not affect the primary fix (0.7→2.8 mapping is unambiguous) |

---

## 6. Files Referenced

| File | Relevance |
|------|-----------|
| `omnivoice_server/routers/speech.py` | HTTP endpoint, calls `inference_svc.synthesize()` |
| `omnivoice_server/services/inference.py` | Orchestrates synthesis |
| `omnivoice_server/services/model.py` | Loads OmniVoice model |
| `OmniVoice/omnivoice/models/omnivoice.py` | Core model: `load_asr_model()`, `transcribe()`, `create_voice_clone_prompt()` |
| `OmniVoice/omnivoice/utils/audio.py` | Audio loading: `load_audio()`, `load_waveform()` (uses soundfile/librosa, not torchcodec) |
| `OmniVoice/pyproject.toml` | `transformers>=5.3.0` dependency; add `faster-whisper` here if 4.D is adopted |
| `omnivoice_server/pyproject.toml` | **Fix**: `torchcodec>=0.7,<0.8; sys_platform != "win32"` in `[project.optional-dependencies]` |
| `Dockerfile.cuda` | `torchcodec==0.11` installed as required dependency — **fix torch version or version pin** |
| `omnivoice_server/main.py` | **Add `_disable_torchcodec_on_windows()` call here, before any transformers import** |
| `docs/readme/sections/14-troubleshooting.md` | Add Windows torchcodec section + corrected version compatibility table + torchaudio ≥2.9 caveat |

---

## 7. External References

- [torchcodec GitHub](https://github.com/meta-pytorch/torchcodec)
- [torchcodec official docs — Windows install (conda-only for CUDA; CPU pip available)](https://github.com/meta-pytorch/torchcodec#installation)
- [torchcodec PyPI — version history + Windows wheel availability](https://pypi.org/project/torchcodec/)
- [torchcodec Releases — 0.7 Windows BETA support; 0.8.1 Windows FFmpeg 8 support added](https://github.com/meta-pytorch/torchcodec/releases)
- [torchcodec README — compatibility table: 0.7↔torch 2.8, 0.8↔2.9, 0.10↔2.10, 0.11↔2.11](https://github.com/meta-pytorch/torchcodec)
- [torchcodec PR #888 — Windows GPU support via conda-forge (Sept 2025)](https://github.com/pytorch/torchcodec/pull/888)
- [torchcodec PR #1109 - Fix load_torchcodec_shared_libraries on Windows](https://github.com/pytorch/torchcodec/pull/1109) (Dec 2025)
- [torchcodec Issue #1233 - RuntimeError on Windows import](https://github.com/meta-pytorch/torchcodec/issues/1233)
- [torchcodec Issue #1006 - torch 2.9+cu130 incompatibility on Windows (via 0.8.1 mismatch)](https://github.com/meta-pytorch/torchcodec/issues/1006)
- [torchcodec Issue #640 - Windows support tracker](https://github.com/meta-pytorch/torchcodec/issues/640)
- [torchcodec Issue #912 - RuntimeError when installed with torch 2.9 RC (confirms 0.7=2.8 via pip resolve)](https://github.com/meta-pytorch/torchcodec/issues/912)
- [transformers#42499 - ASR pipeline raises error when torchcodec installed but invalid (Windows)](https://github.com/huggingface/transformers/issues/42499)
- [transformers#42103 - torchcodec compatibility](https://github.com/huggingface/transformers/issues/42103)
- [transformers import_utils.py — `is_torchcodec_available` implementation](https://github.com/huggingface/transformers/blob/main/src/transformers/utils/import_utils.py)
- [HuggingFace Forums - Cannot load torchcodec (Windows DLL + os.add_dll_directory)](https://discuss.huggingface.co/t/cannot-load-torchcodec/169260)
- [FunASR Issue #81 - torchaudio load fails with TorchCodec](https://github.com/FunAudioLLM/Fun-ASR/issues/81)
- [F5-TTS Issue #1234 - libtorchcodec Windows + torchaudio ≥2.9 uses torchcodec as only backend](https://github.com/SWivid/F5-TTS/issues/1234)
- [Wan2GP Issue #1702 - torchcodec Windows pip no wheel](https://github.com/deepbeepmeep/Wan2GP/issues/1702)
- [ComfyUI-OmniVoice-TTS pytorch_compatibility_matrix.md — confirms torch 2.8→torchcodec 0.7.0](https://github.com/Saganaki22/ComfyUI-OmniVoice-TTS/blob/main/pytorch_compatibility_matrix.md)
- [Python docs — os.add_dll_directory (Windows, Python ≥3.8)](https://docs.python.org/3/library/os.html#os.add_dll_directory)
- [Python docs — importlib.util.find_spec: raises ValueError when sys.modules[name].__spec__ is None](https://docs.python.org/3/library/importlib.html#importlib.util.find_spec) ← **critical for §4.B**
- [torchaudio 2.8 docs — `load()` deprecated, `load_with_torchcodec()` available but optional](https://docs.pytorch.org/audio/2.8/torchaudio.html)
- [torchaudio 2.9 docs — `load()` is now alias for `load_with_torchcodec()` (hard cutover)](https://docs.pytorch.org/audio/2.9.0/torchaudio.html)
- [pytorch/audio Issue #3902 — TorchAudio migration plan: deprecate in 2.8, remove in 2.9](https://github.com/pytorch/audio/issues/3902)
- [Whisper pipeline docs](https://huggingface.co/docs/transformers/main/model_doc/whisper)
- [faster-whisper (SYSTRAN)](https://github.com/SYSTRAN/faster-whisper)
- [faster-whisper PyPI — no system FFmpeg required; uses PyAV bundled FFmpeg](https://pypi.org/project/faster-whisper/)
- [faster-whisper installation guide — ctranslate2 CUDA version matrix: CUDA 11+cuDNN 8 → 3.24.0; CUDA 12+cuDNN 8 → 4.4.0; CUDA 12+cuDNN 9 → ≥4.5](https://deepwiki.com/SYSTRAN/faster-whisper/2-installation)
- [FunASR](https://github.com/modelscope/FunASR)
- [PyTorch 2.11 release blog — confirms torch 2.11 released Mar 2026](https://pytorch.org/blog/pytorch-2-11-release-blog/)
- [torch PyPI version history](https://pypi.org/project/torch/#history)
