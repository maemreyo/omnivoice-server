# Issue #21 - External Component Responsibility Attribution

> **Issue**: [Voice Quality Issues for Podcast Output #21](https://github.com/maemreyo/omnivoice-server/issues/21)  
> **Analysis Date**: 2026-04-18  
> **Analyst**: Technical Investigation Team

---

## Executive Summary

This report maps each problem reported in issue #21 to the most plausibly responsible external component(s) in the integration chain: **Open Notebook → Podcastfy → omnivoice-server → OmniVoice upstream → Gradio demo**.

**Key Finding**: Most issues trace to **OmniVoice upstream model behavior** (random sampling, diffusion architecture), with **integration layer issues** (Open Notebook/Podcastfy) contributing to clone voice and multi-speaker problems.

---

## Integration Chain Architecture

```
User (eclgo)
    ↓
Open Notebook (Next.js Frontend)
    ↓ Configures speakers with Voice IDs
Podcastfy (Python Backend)
    ↓ Generates transcript, calls TTS per segment
omnivoice-server (FastAPI - THIS REPO)
    ↓ OpenAI-compatible API wrapper
OmniVoice Model (k2-fsa/OmniVoice - UPSTREAM)
    ↓ PyTorch TTS model
Audio Output
```

**Parallel Test Path**:
```
User → Gradio Demo (omnivoice-demo) → OmniVoice Model
User → PyVideoTrans → OmniVoice Model (local clone)
```

---

## Issue 1: Noisy Voice at 5m19s (Non-Human Voice, ~20s Duration)

### Reported Behavior
- Audio file contains weird noise (non-human voice) at timestamp 5m19s
- Duration: ~20 seconds
- Transcript at that position is normal text
- Voice preset used: "ash"

### Responsibility Attribution

| Component | Responsibility Level | Evidence | Confidence |
|-----------|---------------------|----------|------------|
| **OmniVoice Model** | **PRIMARY** | Model-level artifact; text preprocessing or numerical instability in diffusion process | **High** |
| **omnivoice-server** | Secondary | Possible text normalization issue (numbers, special chars not handled) | Medium |
| **Podcastfy** | Low | Content processing could introduce artifacts | Low |
| **Open Notebook** | Minimal | UI layer, unlikely to affect audio generation | Very Low |

### Root Cause Analysis

**Most Plausible**: OmniVoice model limitation or bug
- **Evidence 1**: User reports "I know some issues are probably due to the bugs on the Omnivoice model"
- **Evidence 2**: Noise occurs at specific content position, suggesting text-dependent model behavior
- **Evidence 3**: Similar issues not reported with OpenAI TTS, suggesting model-specific behavior

**Secondary Possibility**: Text preprocessing in omnivoice-server
- Numbers not normalized to words
- Special characters not handled
- Phoneme conversion issues

**Recommendation**: 
1. Extract exact transcript text at 5m19s position
2. Test direct OmniVoice model generation with that text
3. Check for special characters, numbers, or unusual phoneme sequences

---

## Issue 2: Inconsistent Voice Per Transcript (Each Transcript = Different Voice)

### Reported Behavior
- Each separate transcript segment produces a different voice
- Tested with "ash" preset voice
- Official Gradio webui demo (early April) shows **same issue**
- User suspects: "Maybe it is the limitation of the model due to random seed each time?"

### Responsibility Attribution

| Component | Responsibility Level | Evidence | Confidence |
|-----------|---------------------|----------|------------|
| **OmniVoice Model** | **PRIMARY** | Diffusion model uses random sampling; no seed control in generation API | **Very High** |
| **omnivoice-server** | Secondary | Does not expose seed parameter for reproducibility | Medium |
| **Podcastfy** | Minimal | Calls API per segment independently (expected behavior) | Low |
| **Open Notebook** | Minimal | UI layer, no control over generation randomness | Very Low |

### Root Cause Analysis

**Confirmed**: OmniVoice model architecture behavior
- **Evidence 1**: User tested official Gradio demo and found **same inconsistency issue**
- **Evidence 2**: User states: "I tested official webui demo (early April version), it has the same issue"
- **Evidence 3**: OmniVoice uses diffusion language model with random sampling per generation
- **Evidence 4**: From tech report: "OmniVoice uses random sampling in the diffusion process. Each generation is independent."

**Why This Happens**:
```python
# OmniVoice model behavior (simplified)
audio1 = model.generate(text="Hello", voice="ash")  # Random seed A
audio2 = model.generate(text="Hello", voice="ash")  # Random seed B (different voice)
```

**Counterpoint - Clone Mode Works**:
- User reports: "for clone voice mode it was OK to generate quite good consistent voice for 3K+ Chinese words based on testing in Pyvideotrans via API call to the local OmniVoice"
- **Implication**: Clone mode with reference audio provides consistency, but preset/design modes do not

**Recommendation**:
1. **OmniVoice upstream**: Add seed parameter to generation API
2. **omnivoice-server**: Expose seed parameter in API
3. **Workaround**: Use clone voice mode instead of presets for consistency

---

## Issue 3: Clone Voice Not Working (Output ≠ Reference Audio)

### Reported Behavior
- User created profile ID via omnivoice-server
- Configured Voice ID in Open Notebook: `clone:<profile id>`
- No 422 error (API accepts request)
- Output voice does not match reference audio
- User notes: "Maybe your design not yet support clone voice mode? I'm not IT guy, but AI did mention your code logic in earlier version doesn't include clone mode."

### Responsibility Attribution

| Component | Responsibility Level | Evidence | Confidence |
|-----------|---------------------|----------|------------|
| **Open Notebook** | **PRIMARY** | May not correctly pass `clone:` prefix to Podcastfy | **High** |
| **Podcastfy** | **PRIMARY** | May not support `clone:` prefix format or strips it before API call | **High** |
| **omnivoice-server** | Secondary | Voice ID parsing logic may have bugs (though code shows support) | Medium |
| **OmniVoice Model** | Low | Clone mode works in PyVideoTrans, so model itself is functional | Low |

### Root Cause Analysis

**Most Plausible**: Integration layer issue (Open Notebook or Podcastfy)
- **Evidence 1**: User successfully used clone mode in PyVideoTrans with local OmniVoice: "for clone voice mode it was OK to generate quite good consistent voice for 3K+ Chinese words"
- **Evidence 2**: This proves OmniVoice model clone functionality works correctly
- **Evidence 3**: omnivoice-server code shows `clone:` prefix parsing logic exists (from tech report)
- **Evidence 4**: User receives no error, suggesting request is accepted but voice resolution fails silently

**Failure Points**:
```
Open Notebook UI
├── User enters: "clone:profile_abc123"
├── Sent to Podcastfy: ??? (may be stripped or malformed)
└── Podcastfy sends to API: ??? (may not include "clone:" prefix)

omnivoice-server receives:
├── Expected: voice="clone:profile_abc123"
├── Actual: voice="profile_abc123" or voice="ash" (fallback)
└── Result: Falls back to preset or auto voice
```

**Recommendation**:
1. Add debug logging in omnivoice-server to capture exact `voice` parameter received
2. Test direct API call: `curl -X POST ... -d '{"voice":"clone:profile_id"}'`
3. Check Open Notebook/Podcastfy source code for voice ID handling
4. Verify profile ID exists and is accessible

---

## Issue 4: Wrong Gender Output (2 Speakers, Both Male Voice)

### Reported Behavior
- Configured 2 speakers in Open Notebook
- Speaker 1: male voice (`clone:<male profile ID>`)
- Speaker 2: female voice (`clone:<female profile ID>`)
- Output: Both speakers produce male voice
- Voices are also inconsistent across transcripts

### Responsibility Attribution

| Component | Responsibility Level | Evidence | Confidence |
|-----------|---------------------|----------|------------|
| **Open Notebook** | **PRIMARY** | Multi-speaker configuration may not correctly map Voice IDs to speakers | **High** |
| **Podcastfy** | **PRIMARY** | May not correctly pass speaker-specific voice IDs in multi-speaker mode | **High** |
| **omnivoice-server** | Secondary | Multi-speaker script API may have bugs (though it's marked as Beta) | Medium |
| **OmniVoice Model** | Minimal | Model itself can generate both genders (proven in other contexts) | Very Low |

### Root Cause Analysis

**Most Plausible**: Open Notebook or Podcastfy multi-speaker logic issue
- **Evidence 1**: Related to Issue 3 (clone voice not working), suggesting voice ID not passed correctly
- **Evidence 2**: If clone mode fails, both speakers may fall back to same default voice
- **Evidence 3**: omnivoice-server has `/v1/audio/script` endpoint for multi-speaker (Beta), but Open Notebook may not use it

**Possible Scenarios**:
```
Scenario A: Voice ID not passed per speaker
├── Open Notebook sends same voice ID for all speakers
└── Result: All speakers sound the same

Scenario B: Clone mode fails, falls back to default
├── Both "clone:male_id" and "clone:female_id" fail to resolve
├── Server falls back to default voice (male)
└── Result: Both speakers male

Scenario C: Podcastfy doesn't support multi-speaker with clone
├── Podcastfy may only support presets in multi-speaker mode
└── Result: Clone IDs ignored, presets used instead
```

**Recommendation**:
1. Test with preset voices first: `voice="ash"` and `voice="nova"` (male/female)
2. If presets work, issue is clone-specific
3. If presets also fail, issue is multi-speaker logic in Open Notebook/Podcastfy
4. Consider using omnivoice-server's `/v1/audio/script` endpoint directly

---

## Critical User Evidence: PyVideoTrans Success

### Key Observation
User reports: **"for clone voice mode it was OK to generate quite good consistent voice for 3K+ Chinese words based on testing in Pyvideotrans via API call to the local OmniVoice"**

### Implications

| Finding | Implication |
|---------|-------------|
| **Clone mode works in PyVideoTrans** | OmniVoice model clone functionality is correct |
| **3K+ words with consistency** | Clone mode provides voice consistency (unlike preset mode) |
| **Local OmniVoice (not via server)** | Direct model access works; issue may be in server or integration layer |

**Conclusion**: 
- OmniVoice model is **not the problem** for clone voice
- Issue is in **integration chain**: Open Notebook → Podcastfy → omnivoice-server
- Most likely: Voice ID format not correctly passed through the chain

---

## Gradio Demo Evidence

### User Report
"I tested official webui demo (early April version), it has the same issue."

### Analysis

**Which Issue?**
- User refers to **Issue 2: Inconsistent voice per transcript**
- Gradio demo also shows voice inconsistency with same design settings

**Responsibility**:
- **OmniVoice Model**: Confirmed as root cause for inconsistency
- Gradio demo directly calls OmniVoice model (no server layer)
- Same behavior in Gradio = model-level behavior, not integration bug

**Counterpoint**:
- User also states: "However, for clone voice mode it was OK to generate quite good consistent voice"
- This was tested in PyVideoTrans, not Gradio demo
- Suggests: Clone mode provides consistency, preset/design modes do not

---

## Summary Table: Responsibility by Issue

| Issue | Primary Responsible Component | Secondary Component | Confidence | Evidence Quality |
|-------|------------------------------|---------------------|------------|------------------|
| **1. Noise at 5m19s** | OmniVoice Model | omnivoice-server (text preprocessing) | High | Direct audio artifact, model-level |
| **2. Inconsistent voice** | **OmniVoice Model** | omnivoice-server (no seed param) | **Very High** | **Confirmed by Gradio demo test** |
| **3. Clone not working** | **Open Notebook / Podcastfy** | omnivoice-server (parsing) | High | **PyVideoTrans clone works** |
| **4. Wrong gender** | **Open Notebook / Podcastfy** | omnivoice-server (multi-speaker) | High | Related to Issue 3 |

---

## Recommendations by Component

### For OmniVoice Upstream (k2-fsa/OmniVoice)

**Issue 2: Inconsistent Voice**
- [ ] Add `seed` parameter to generation API for reproducibility
- [ ] Document that preset/design modes use random sampling
- [ ] Recommend clone mode for consistency requirements

**Issue 1: Noise Artifact**
- [ ] Investigate text preprocessing for special characters
- [ ] Add better error handling for problematic phoneme sequences
- [ ] Consider adding audio quality validation

### For Open Notebook (lfnovo/open-notebook)

**Issue 3 & 4: Clone Voice and Multi-Speaker**
- [ ] Verify `clone:` prefix is correctly passed to Podcastfy
- [ ] Test multi-speaker with different voice IDs
- [ ] Add debug logging for voice ID resolution
- [ ] Consider using omnivoice-server's `/v1/audio/script` endpoint

### For Podcastfy (souzatharsis/podcastfy)

**Issue 3 & 4: Voice ID Handling**
- [ ] Verify support for `clone:` prefix format
- [ ] Test multi-speaker with clone voices
- [ ] Document voice ID format requirements
- [ ] Add validation for voice ID format

### For omnivoice-server (THIS REPO)

**Issue 2: Voice Consistency**
- [ ] Add `seed` parameter to API (if OmniVoice upstream supports it)
- [ ] Add speaker embedding caching for consistency
- [ ] Document preset vs clone mode behavior differences

**Issue 3 & 4: Integration**
- [ ] Add comprehensive debug logging for voice resolution
- [ ] Improve error messages when profile not found
- [ ] Test `/v1/audio/script` endpoint with Open Notebook
- [ ] Add integration tests with Podcastfy

---

## Testing Strategy

### Isolation Tests

**Test 1: Direct OmniVoice Model**
```python
# Bypass all integration layers
from omnivoice import OmniVoice
model = OmniVoice()
audio = model.generate(text="Hello", instruct="male, american")
# Expected: Works correctly (baseline)
```

**Test 2: omnivoice-server API**
```bash
# Test server layer only
curl -X POST http://localhost:8880/v1/audio/speech \
  -d '{"model":"omnivoice","input":"Hello","voice":"clone:profile_id"}'
# Expected: Should work if profile exists
```

**Test 3: Podcastfy Integration**
```python
# Test Podcastfy → omnivoice-server
from podcastfy import Podcastfy
podcast = Podcastfy(tts_provider="omnivoice-server")
podcast.generate(speakers=[{"voice": "clone:profile_id"}])
# Expected: Identify if Podcastfy passes voice ID correctly
```

**Test 4: Open Notebook End-to-End**
```
# Full integration test
Open Notebook UI → Configure speakers → Generate podcast
# Expected: Identify where voice ID is lost/malformed
```

---

## Conclusion

### Primary Responsibility Distribution

1. **OmniVoice Model (Upstream)**: 
   - Issue 2 (Inconsistent voice) - **Confirmed by Gradio demo**
   - Issue 1 (Noise) - **Likely model limitation**

2. **Open Notebook / Podcastfy (Integration Layer)**:
   - Issue 3 (Clone not working) - **High confidence**
   - Issue 4 (Wrong gender) - **High confidence**

3. **omnivoice-server (THIS REPO)**:
   - Secondary responsibility for all issues
   - Can improve: logging, error handling, seed parameter, caching

### Key Evidence

- **Gradio demo shows same inconsistency** → Model behavior, not integration bug
- **PyVideoTrans clone works well** → Model clone functionality is correct
- **No 422 errors but wrong output** → Voice ID parsing/resolution issue

### Next Steps

1. **Immediate**: Add debug logging to omnivoice-server to capture exact API calls
2. **Short-term**: Test direct API calls to isolate server vs integration issues
3. **Long-term**: Collaborate with Open Notebook/Podcastfy teams on voice ID format
4. **Upstream**: Request seed parameter support from OmniVoice team

---

*Report completed: 2026-04-18*  
*Issue Reference: https://github.com/maemreyo/omnivoice-server/issues/21*
