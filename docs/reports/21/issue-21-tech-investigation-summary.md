# Issue #21 - Technology Investigation Summary

> **Issue**: [Voice Quality Issues for Podcast Output #21](https://github.com/maemreyo/omnivoice-server/issues/21)  
> **Research Date**: 2026-04-18  
> **Reporter**: @eclgo

---

## Executive Summary

Issue #21 reports 4 main problems when using Open Notebook with OmniVoice-server:

1. **Noisy voice** at position 5m19s in the podcast
2. **Inconsistent voice** - Each transcript produces a different voice
3. **Clone voice not working** - Output does not match reference audio
4. **Wrong gender** - 2 speakers (male/female) both output male voice

The related tech stacks investigated include: **Open Notebook**, **Podcastfy**, **OmniVoice**, **OmniVoice-server**, **Gradio**, and **OpenAI TTS API**.

---

## Tech Stack Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TECH STACK DIAGRAM                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐              │
│  │   User       │────▶│  Open        │────▶│  Podcastfy   │              │
│  │  (eclgo)     │     │  Notebook    │     │  (Backend)   │              │
│  └──────────────┘     │  (Next.js)   │     │  (Python)    │              │
│                       └──────────────┘     └──────┬───────┘              │
│                                                   │                        │
│                                                   ▼                        │
│                       ┌──────────────┐     ┌──────────────┐              │
│                       │  OmniVoice   │◀────│ OmniVoice    │              │
│                       │  Demo        │     │ -server      │              │
│                       │  (Gradio)    │     │ (FastAPI)    │              │
│                       └──────────────┘     └──────┬───────┘              │
│                                                   │                        │
│                                                   ▼                        │
│                                          ┌──────────────┐                │
│                                          │  OmniVoice   │                │
│                                          │  Model       │                │
│                                          │  (PyTorch)   │                │
│                                          └──────────────┘                │
│                                                                             │
│  API Standards:                                                             │
│  - Open Notebook / Podcastfy use OpenAI TTS API format                     │
│  - OmniVoice-server implements OpenAI-compatible API                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack Details

### 1. Open Notebook ([open-notebook.ai](https://www.open-notebook.ai/))

| Aspect | Details |
|--------|---------|
| **Type** | Web application (Next.js frontend) |
| **Purpose** | AI podcast generator - alternative to Google NotebookLM |
| **Core Engine** | Podcastfy |
| **TTS Providers** | OpenAI, Gemini, ElevenLabs, OmniVoice-server |
| **Key Feature** | Custom speaker profiles with Voice ID |

**Relevance to Issue #21**:
- User configures speaker with Voice ID: `clone:profile_id` or preset (`ash`, `nova`, etc.)
- Sends requests to OmniVoice-server via Podcastfy backend

### 2. Podcastfy ([github.com/souzatharsis/podcastfy](https://github.com/souzatharsis/podcastfy))

| Aspect | Details |
|--------|---------|
| **Type** | Python library |
| **Purpose** | Transform content into AI podcast conversations |
| **Used By** | Open Notebook, OpenPod, SurfSense |
| **TTS Integration** | OpenAI, Google, ElevenLabs, Microsoft |

**Relevance to Issue #21**:
- Handles workflow: content → transcript → audio segments → mixed podcast
- Calls TTS API for each individual speaker segment

### 3. OmniVoice ([k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice))

| Aspect | Details |
|--------|---------|
| **Type** | PyTorch TTS Model |
| **Languages** | 600+ |
| **Features** | Voice cloning, voice design, auto voice |
| **Architecture** | Diffusion language model |
| **RTF** | 0.025-0.2 (GPU) |

**Relevance to Issue #21**:
- **Issue 2 (Inconsistent voice)**: Model uses random sampling each time it generates
- **Issue 3 (Clone voice)**: Could be an integration issue, not a model bug
- **Issue 1 (Noise)**: Could be a model limitation or text preprocessing

### 4. OmniVoice-server ([maemreyo/omnivoice-server](https://github.com/maemreyo/omnivoice-server))

| Aspect | Details |
|--------|---------|
| **Type** | FastAPI HTTP server |
| **API** | OpenAI-compatible |
| **Version** | 0.2.0 |
| **Features** | Voice cloning, design, streaming, multi-speaker script |

**Relevance to Issue #21**:
- Is the integration point between Open Notebook and OmniVoice model
- Need to verify: voice ID parsing, clone: prefix handling, multi-speaker logic

### 5. Gradio ([gradio.app](https://www.gradio.app/))

| Aspect | Details |
|--------|---------|
| **Type** | Python web UI library |
| **Used By** | OmniVoice demo (`omnivoice-demo`) |
| **Purpose** | Interactive ML model demos |

**Relevance to Issue #21**:
- User tested with "official webui demo" and found the same issue
- Confirms the issue could be model behavior, not a server bug

### 6. OpenAI TTS API

| Aspect | Details |
|--------|---------|
| **Format** | Standard API implemented by OmniVoice-server |
| **Voices** | 13 presets (alloy, ash, nova, etc.) |
| **Features** | Speed control, multiple formats |

**Relevance to Issue #21**:
- OmniVoice-server provides OpenAI-compatible API
- Podcastfy/Open Notebook expect OpenAI format

---

## Issue Analysis by Tech Stack

### Issue 1: Weird Noise at 5m19s

```
Hypothesis Tree:
├── OmniVoice Model Layer
│   ├── Numerical instability with specific phonemes
│   ├── Long-form generation boundary artifact
│   └── Cross-lingual accent interference
│
├── OmniVoice-server Layer
│   ├── Text preprocessing issue (numbers/special chars)
│   ├── Audio encoding issue
│   └── Chunking boundary problem
│
└── Open Notebook/Podcastfy Layer
    └── Content processing artifact
```

**Likely Root Cause**: Text preprocessing or model limitation with specific content at 5m19s.

### Issue 2: Inconsistent Voice Per Transcript

```
Root Cause: OmniVoice Diffusion Model Architecture

OmniVoice.generate():
├── Random seed for each call
├── Independent sampling process
└── No speaker embedding caching

Result: Each API call = different voice (in auto mode)
```

**Solution Options**:
1. Add seed parameter for reproducibility
2. Cache speaker embeddings
3. Use voice cloning instead of auto voice
4. Use voice design with specific attributes

### Issue 3: Clone Voice Not Working

```
Data Flow Analysis:

Open Notebook
├── User enters: "clone:profile_abc123" in Voice ID field
├── Podcastfy receives: {speaker: "Host", voice: "clone:profile_abc123"}
└── Calls TTS API

OmniVoice-server
├── Receives: voice="clone:profile_abc123"
├── Parser: if voice.startswith("clone:") → clone mode
├── Lookup profile_id = "profile_abc123"
└── Call model.clone(ref_audio_path)

Potential Failure Points:
1. ❌ Prefix not passed correctly
2. ❌ Profile ID does not exist
3. ❌ Profile lookup fails
4. ❌ Model falls back to auto mode
```

**Investigation Needed**:
- Log actual API calls from Podcastfy
- Verify profile exists and is accessible
- Test direct API call

### Issue 4: Wrong Gender Output

```
Scenario: 2 speakers configured
├── Speaker 1: male voice (or "clone:male_profile")
├── Speaker 2: female voice (or "clone:female_profile")
└── Output: Both sound male

Possible Causes:
1. Voice ID not passed correctly for speaker 2
2. Voice resolution defaults to male
3. Podcastfy merges segments or uses the same voice
4. OmniVoice-server does not apply design attributes
```

**Investigation Needed**:
- Check multi-speaker script in Open Notebook
- Verify voice IDs are sent correctly
- Test with `/v1/audio/script` endpoint

---

## Root Cause Summary

| Issue | Component | Likely Cause | Confidence |
|-------|-----------|--------------|------------|
| **Noise at 5m19s** | Model/Preprocessing | Text normalization or model limitation | Medium |
| **Inconsistent voice** | Model | Random sampling in diffusion | **High** |
| **Clone not working** | Integration | Voice ID parsing or profile lookup | Medium |
| **Wrong gender** | Integration/Podcastfy | Voice ID not passed correctly | Medium |

---

## Recommendations

### Immediate Actions

1. **Add Debug Logging to OmniVoice-server**
   ```python
   # Log all incoming requests
   # Log voice resolution steps
   # Log model parameters
   ```

2. **Create Test Harness**
   ```bash
   # Test script to reproduce each issue
   ./scripts/test_issue_21.sh
   ```

3. **Verify Open Notebook Integration**
   - Capture actual HTTP requests
   - Check voice ID format

4. **Add Seed Parameter**
   ```python
   # Allow reproducible generation
   synthesize(..., seed=42)
   ```

### Short-term Fixes

1. **Voice Consistency Mode**: Cache speaker embeddings
2. **Better Error Handling**: Return 400 for invalid voice IDs
3. **Multi-speaker Optimization**: Use script API

### Long-term Improvements

1. **Word-level Streaming**: For better real-time experience
2. **Batch API**: For large-scale synthesis
3. **SSML Support**: For precise control

---

## Individual Tech Reports

| Tech | Report File |
|------|-------------|
| Open Notebook | `docs/reports/tech-open-notebook.md` |
| Podcastfy | `docs/reports/tech-podcastfy.md` |
| OmniVoice | `docs/reports/tech-omnivoice.md` |
| OmniVoice-server | `docs/reports/tech-omnivoice-server.md` |
| Gradio | `docs/reports/tech-gradio.md` |
| OpenAI TTS API | `docs/reports/tech-openai-tts-api.md` |

---

## Conclusion

Issue #21 is a complex integration issue related to multiple tech stacks. The main problems are:

1. **Inconsistent voice** is expected behavior of the OmniVoice model (random sampling)
2. **Clone voice and gender issues** could be integration problems between Open Notebook/Podcastfy and OmniVoice-server
3. **Noise artifact** needs additional investigation to determine root cause

To fully resolve, requires:
- Close collaboration with Open Notebook team
- Detailed integration testing
- May need additional features in OmniVoice-server (seed control, better logging)

---

*Summary report generated for issue #21 investigation*  
*Research completed: 2026-04-18*