# Issue #21 Code Path Findings - omnivoice-server

## Summary
Concrete code paths for issue #21 user flow: profile creation, /v1/audio/speech, /v1/audio/script, and voice resolution behavior.

---

## 1. Profile Creation & Listing

### POST /v1/voices/profiles
**File**: `omnivoice_server/routers/voices.py:89-133`

**Flow**:
1. Accepts `profile_id`, `ref_audio` (file upload), `ref_text` (optional), `overwrite` flag
2. Validates profile_id pattern: `^[a-zA-Z0-9_-]{1,64}$`
3. Reads upload with size limit: `cfg.max_ref_audio_bytes`
4. Validates audio format via `validate_audio_bytes()`
5. Calls `ProfileService.save_profile()` → writes to disk:
   - `<profile_dir>/<profile_id>/ref_audio.wav`
   - `<profile_dir>/<profile_id>/meta.json` (contains `name`, `ref_text`, `created_at`)
6. Returns 201 with metadata or 409 if exists (without overwrite)

**Key Code**:
```python
# voices.py:121-126
meta = profile_svc.save_profile(
    profile_id=profile_id,
    audio_bytes=audio_bytes,
    ref_text=ref_text,
    overwrite=overwrite,
)
```

### GET /v1/voices
**File**: `omnivoice_server/routers/voices.py:40-83`

**Returns**:
- Built-in voices: `auto`, `design:<attributes>`, OpenAI presets (`alloy`, `ash`, `nova`, etc.)
- Clone voices: `clone:<profile_id>` for each saved profile
- Design attributes list
- Total count

**Key Code**:
```python
# voices.py:67-77
profiles = profile_svc.list_profiles()
clone_voices = [
    {
        "id": f"clone:{p['profile_id']}",
        "type": "clone",
        "profile_id": p["profile_id"],
        ...
    }
    for p in profiles
]
```

---

## 2. Single-Speaker Speech Synthesis

### POST /v1/audio/speech
**File**: `omnivoice_server/routers/speech.py:146-240`

**Request Body** (SpeechRequest):
- `input`: text (1-10,000 chars)
- `voice`: voice identifier (default: "auto")
- `speaker`: alternative to `voice` (checked first)
- `instructions`: explicit design instructions
- `response_format`: wav/mp3/opus/flac/pcm
- `speed`: 0.25-4.0
- `stream`: boolean
- Advanced params: `num_step`, `guidance_scale`, `denoise`, etc.

**Voice Resolution Flow** (`_resolve_synthesis_mode`, line 95-143):

```python
def _resolve_synthesis_mode(body, profile_svc):
    speaker_raw = body.speaker.strip() if body.speaker else None
    voice_raw = body.voice.strip() if body.voice else None
    
    # Priority 1: Check speaker or voice for profile
    profile_to_check = speaker_raw or voice_raw
    if profile_to_check:
        profile_id = profile_to_check
        explicit_clone = profile_id.lower().startswith("clone:")
        if explicit_clone:
            profile_id = profile_id.split(":", 1)[1]
        
        try:
            ref_audio_path = profile_svc.get_ref_audio_path(profile_id)
            ref_text = profile_svc.get_ref_text(profile_id)
            return "clone", None, str(ref_audio_path), ref_text
        except ProfileNotFoundError:
            if explicit_clone:
                raise HTTPException(404, "Profile not found")
            # Implicit lookup failed, fall through to design/preset
    
    # Priority 2: Explicit instructions
    if body.instructions is not None:
        canonicalized = validate_and_canonicalize_instructions(body.instructions)
        return "design", canonicalized, None, None
    
    # Priority 3: OpenAI presets (speaker or voice)
    speaker_key = speaker_raw.strip().lower() if speaker_raw else None
    voice_key = voice_raw.strip().lower() if voice_raw else None
    
    if speaker_key and speaker_key in OPENAI_VOICE_PRESETS:
        return "design", OPENAI_VOICE_PRESETS[speaker_key], None, None
    
    if voice_key and voice_key in OPENAI_VOICE_PRESETS:
        return "design", OPENAI_VOICE_PRESETS[voice_key], None, None
    
    # Priority 4: Default fallback
    return "design", DEFAULT_DESIGN_INSTRUCTIONS, None, None
```

**Key Behaviors**:
1. `speaker` parameter takes precedence over `voice`
2. Both `speaker` and `voice` can trigger profile lookup (with or without `clone:` prefix)
3. Explicit `clone:` prefix → 404 if profile not found
4. Implicit profile name (no prefix) → silent fallback to design/preset if not found
5. `instructions` parameter overrides voice/speaker for design mode
6. OpenAI presets checked in both `speaker` and `voice` fields
7. Final fallback: `DEFAULT_DESIGN_INSTRUCTIONS`

**Synthesis**:
- Builds `SynthesisRequest` with resolved mode/instruct/ref_audio_path
- Calls `InferenceService.synthesize()` → thread pool → `model.generate()`
- Returns audio bytes with headers: `X-Audio-Duration-S`, `X-Synthesis-Latency-S`

---

## 3. Multi-Speaker Script Synthesis

### POST /v1/audio/script
**File**: `omnivoice_server/routers/script.py:109-224`

**Request Body** (ScriptRequest):
- `script`: list of segments (1-100), each with:
  - `speaker`: speaker ID (alphanumeric/dash/underscore, 1-64 chars)
  - `text`: segment text (1-10,000 chars)
  - `voice`: optional voice override per segment
  - `speed`: optional speed override per segment
- `default_voice`: fallback voice for all speakers
- `speed`: base speed (0.25-4.0)
- `response_format`: wav/mp3/opus/flac
- `output_format`: "single_track" or "multi_track"
- `pause_between_speakers`: 0-5 seconds
- `on_error`: "abort" or "skip"

**Validation**:
- Max 100 segments
- Max 50,000 total characters
- Max 10 unique speakers
- Speaker ID pattern: `^[a-zA-Z0-9_-]{1,64}$`

**Voice Resolution** (`ScriptOrchestrator._resolve_voices`, script.py:155-220):

```python
async def _resolve_voices(segments, default_voice):
    speaker_voices = {}
    
    for segment in segments:
        speaker = segment.speaker
        
        # Skip if already resolved (first-definition inheritance)
        if speaker in speaker_voices:
            continue
        
        # Determine voice for this speaker
        if segment.voice:
            voice = segment.voice
        elif default_voice:
            voice = default_voice
        else:
            voice = settings.default_voice
        
        # Validate clone profiles upfront
        if voice.startswith("clone:"):
            profile_id = voice.split(":", 1)[1]
            try:
                ref_audio_path = profiles.get_ref_audio_path(profile_id)
            except ProfileNotFoundError:
                raise HTTPException(422, f"Clone profile not found: {profile_id}")
            speaker_voices[speaker] = ResolvedVoice(
                kind="clone",
                value=profile_id,
                ref_audio_path=ref_audio_path,
            )
            continue
        
        # Validate OpenAI presets upfront
        if voice.startswith("openai:"):
            preset_name = voice.split(":", 1)[1]
            instruct = OPENAI_VOICE_PRESETS.get(preset_name)
            if not instruct:
                raise HTTPException(422, f"Invalid OpenAI preset: {preset_name}")
            speaker_voices[speaker] = ResolvedVoice(kind="design", value=instruct)
            continue
        
        # Design voices (validated lazily at synthesis)
        speaker_voices[speaker] = ResolvedVoice(kind="design", value=voice)
    
    return speaker_voices
```

**Key Behaviors**:
1. **First-definition inheritance**: First segment with speaker X defines voice for all X segments
2. Voice priority per segment: `segment.voice` > `default_voice` > `settings.default_voice`
3. **Upfront validation**: Clone profiles and OpenAI presets validated before synthesis
4. **Explicit prefixes required**: `clone:` and `openai:` prefixes are mandatory in script API
5. Design voices (no prefix) validated lazily during synthesis

**Synthesis Flow**:
1. Resolve all speaker→voice mappings upfront
2. Estimate total duration (0.08s per char / speed + pauses)
3. Reject if estimated duration > 600s
4. Synthesize segments sequentially with pause insertion on speaker change
5. Error handling: "abort" stops on first error, "skip" continues and tracks skipped indices
6. Returns either:
   - **single_track**: Binary audio with metadata headers
   - **multi_track**: JSON with base64-encoded per-speaker tracks + timestamps

**Response Headers**:
- `X-Audio-Duration-S`
- `X-Synthesis-Latency-S`
- `X-Speakers-Unique`
- `X-Segment-Count`
- `X-Skipped-Segments` (comma-separated indices)

---

## 4. Key Differences: /speech vs /script

| Aspect | /v1/audio/speech | /v1/audio/script |
|--------|------------------|------------------|
| **Voice parameter** | `voice` or `speaker` (interchangeable) | `voice` per segment + `default_voice` |
| **Profile lookup** | Implicit (tries with/without `clone:`) | Explicit (`clone:` prefix required) |
| **Preset format** | Bare name (`ash`, `nova`) | `openai:ash`, `openai:nova` |
| **Error on missing profile** | 404 if explicit `clone:`, silent fallback otherwise | 422 always (upfront validation) |
| **Multi-speaker** | Single voice per request | Multiple speakers with inheritance |
| **Streaming** | Supported (PCM only) | Not supported |
| **Output formats** | wav/mp3/opus/flac/pcm | single_track or multi_track |

---

## 5. Ambiguities & Client-Side Dependencies

### Ambiguity 1: Open Notebook Voice ID Format
**Unknown**: Does Open Notebook send `clone:profile_id` or just `profile_id`?

**Server Behavior**:
- `/v1/audio/speech`: Accepts both formats, tries implicit lookup
- `/v1/audio/script`: Requires explicit `clone:` prefix

**Impact**: If Open Notebook sends bare `profile_id` to `/v1/audio/script`, it will be treated as design voice, not clone.

### Ambiguity 2: Podcastfy Endpoint Choice
**Unknown**: Does Podcastfy use `/v1/audio/speech` (per-segment) or `/v1/audio/script` (batch)?

**Server Behavior**:
- `/v1/audio/speech`: Called once per segment, no speaker inheritance
- `/v1/audio/script`: Called once for entire script, speaker inheritance applies

**Impact**: If using `/speech`, each segment is independent. If using `/script`, first segment defines voice for each speaker.

### Ambiguity 3: Multi-Speaker Voice Assignment
**Unknown**: How does Open Notebook map speaker names to voice IDs in multi-speaker mode?

**Server Behavior**:
- `/v1/audio/script` expects `speaker` field per segment
- Voice resolution uses first-definition inheritance
- No validation that different speakers have different voices

**Impact**: If Open Notebook sends same voice for all speakers, server will use that voice for all.

### Ambiguity 4: Preset vs Clone in Multi-Speaker
**Unknown**: Does Open Notebook use presets or clone profiles for multi-speaker podcasts?

**Server Behavior**:
- Presets: Use `openai:ash`, `openai:nova` in `/script` API
- Clone: Use `clone:profile_id` in `/script` API
- Bare names treated as design instructions

**Impact**: Format mismatch will cause voice resolution to fail or use wrong mode.

---

## 6. Concrete Code Paths for Issue #21 Scenarios

### Scenario A: Clone Voice Not Working (Issue #3)
**User Action**: Create profile, set Voice ID to `clone:profile_id` in Open Notebook

**Possible Failure Points**:
1. **Open Notebook sends**: `voice="profile_id"` (no prefix) to `/v1/audio/speech`
   - Server tries implicit lookup → succeeds → clone mode works ✓
   
2. **Open Notebook sends**: `voice="profile_id"` (no prefix) to `/v1/audio/script`
   - Server treats as design voice → wrong mode ✗
   
3. **Open Notebook sends**: `voice="clone:profile_id"` but profile doesn't exist
   - `/speech`: 404 error ✗
   - `/script`: 422 error ✗
   
4. **Podcastfy strips prefix**: Sends `voice="profile_id"` after stripping `clone:`
   - Depends on endpoint (see #1 and #2)

**Server-side verification needed**: Add logging to capture exact `voice` parameter received.

### Scenario B: Wrong Gender (Issue #4)
**User Action**: Configure 2 speakers with different voices

**Possible Failure Points**:
1. **Using /v1/audio/speech per segment**:
   - Each segment independent, no speaker inheritance
   - If voice not specified per segment → uses default
   - Both speakers get same default voice ✗
   
2. **Using /v1/audio/script with first-definition inheritance**:
   - First segment for speaker A defines voice for all A segments
   - If first segment has wrong voice → all segments wrong ✗
   
3. **Open Notebook sends same voice for both speakers**:
   - Server correctly uses that voice for both
   - Not a server bug, client configuration issue ✗

**Server-side verification needed**: Log speaker→voice mapping in script API.

### Scenario C: Inconsistent Voice (Issue #2)
**User Action**: Generate same text multiple times with preset voice

**Server Behavior**:
- Server passes `instruct` to `model.generate()`
- Model uses random sampling (no seed control)
- Different output each time (expected model behavior)

**Not a server bug**: Model-level behavior confirmed by Gradio demo test.

---

## 7. Recommendations for Server-Side Investigation

### Add Debug Logging
**File**: `omnivoice_server/routers/speech.py` and `script.py`

```python
# In _resolve_synthesis_mode (speech.py)
logger.info(f"Voice resolution: speaker={body.speaker}, voice={body.voice}, "
            f"instructions={body.instructions}, mode={mode}, instruct={instruct}")

# In ScriptOrchestrator._resolve_voices (script.py)
logger.info(f"Script voice resolution: speaker={speaker}, segment.voice={segment.voice}, "
            f"default_voice={default_voice}, resolved={speaker_voices[speaker]}")
```

### Add Response Headers for Debugging
```python
# In /v1/audio/speech response
headers={
    "X-Voice-Mode": mode,  # "clone" or "design"
    "X-Voice-Value": instruct or profile_id,
    ...
}

# In /v1/audio/script response
headers={
    "X-Speaker-Voice-Map": json.dumps({s: v.kind for s, v in speaker_voices.items()}),
    ...
}
```

### Test Direct API Calls
```bash
# Test 1: Clone with explicit prefix
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"Hello","voice":"clone:test_profile"}' \
  --output test1.wav

# Test 2: Clone without prefix (implicit)
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"Hello","voice":"test_profile"}' \
  --output test2.wav

# Test 3: Multi-speaker script with clone
curl -X POST http://localhost:8880/v1/audio/script \
  -H "Content-Type: application/json" \
  -d '{
    "script": [
      {"speaker":"alice","text":"Hello","voice":"clone:female_profile"},
      {"speaker":"bob","text":"Hi","voice":"clone:male_profile"}
    ]
  }' \
  --output test3.wav
```

---

## 8. Conclusion

**Concrete Findings**:
1. Profile creation/listing works as documented
2. `/v1/audio/speech` has flexible voice resolution with implicit profile lookup
3. `/v1/audio/script` requires explicit prefixes and validates upfront
4. First-definition inheritance in script API may cause unexpected behavior
5. No server-side voice consistency mechanism (model uses random sampling)

**Ambiguities Requiring Client-Side Investigation**:
1. Voice ID format sent by Open Notebook (with/without `clone:` prefix)
2. Endpoint choice by Podcastfy (`/speech` vs `/script`)
3. Multi-speaker voice assignment logic in Open Notebook
4. Preset vs clone usage in multi-speaker mode

**Not Server Bugs**:
- Voice inconsistency (Issue #2): Model behavior, confirmed by Gradio demo
- Noise artifact (Issue #1): Likely model or text preprocessing, needs upstream investigation

**Potential Server Issues**:
- Clone voice not working (Issue #3): Depends on voice ID format received
- Wrong gender (Issue #4): Depends on speaker→voice mapping from client

**Next Steps**: Add debug logging and test with actual Open Notebook/Podcastfy requests.
