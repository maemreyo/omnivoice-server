# OmniVoice-server - Tech Report

> **Issue Reference**: [#21 - Voice Quality Issues for Podcast Output](https://github.com/maemreyo/omnivoice-server/issues/21)
> **Research Date**: 2026-04-18
> **GitHub**: [maemreyo/omnivoice-server](https://github.com/maemreyo/omnivoice-server)
> **PyPI**: `omnivoice-server`
> **Current Version**: 0.2.0

---

## Overview

**OmniVoice-server** is an HTTP server wrapper that provides an OpenAI-compatible API for the OmniVoice TTS model. It enables easy integration with existing tools and applications that use the OpenAI TTS format.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        OmniVoice-server                         │
├─────────────────────────────────────────────────────────────────┤
│  HTTP Layer (FastAPI)                                           │
│  ├── /v1/audio/speech           (OpenAI-compatible)            │
│  ├── /v1/audio/speech/clone     (Extended)                     │
│  ├── /v1/audio/script           (Multi-speaker - New)          │
│  ├── /v1/voices/profiles        (Voice cloning persistence)   │
│  ├── /v1/voices                 (List voices)                  │
│  ├── /v1/models                 (List models)                  │
│  ├── /health                    (Health check)                  │
│  └── /metrics                   (Prometheus metrics)           │
├─────────────────────────────────────────────────────────────────┤
│  Service Layer                                                  │
│  ├── InferenceService      (OmniVoice model calls)              │
│  ├── ProfileService        (Voice profile management)           │
│  ├── ScriptService         (Multi-speaker orchestration)        │
│  └── MetricsService        (Metrics collection)                 │
├─────────────────────────────────────────────────────────────────┤
│  Adapter Layer                                                  │
│  └── OmniVoiceAdapter      (Model interaction)                │
├─────────────────────────────────────────────────────────────────┤
│  Model Layer (OmniVoice)                                       │
│  ├── Voice Cloning         (ref_audio + ref_text)               │
│  ├── Voice Design          (instruct attributes)               │
│  └── Auto Voice            (random voice)                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Current Features (v0.2.0)

| Feature | Status | Endpoint |
|---------|--------|----------|
| **OpenAI-compatible TTS** | ✅ Complete | `POST /v1/audio/speech` |
| **Voice Cloning** | ✅ Complete | `POST /v1/voices/profiles` + `voice: "clone:id"` |
| **Voice Design** | ✅ Complete | `voice: "female, british accent"` |
| **Voice Profiles** | ✅ Complete | CRUD `/v1/voices/profiles` |
| **Multi-format Output** | ✅ Complete | mp3, wav, opus, flac, aac, pcm |
| **Streaming** | ✅ Sentence-level | `stream: true` |
| **Multi-speaker Script** | 🟡 New (Beta) | `POST /v1/audio/script` |
| **Batch Inference** | ❌ Missing | Planned |
| **Word-level Streaming** | ❌ Missing | Planned |

---

## API Endpoints

### Core Endpoints

```python
# Speech synthesis
POST /v1/audio/speech
├── model: "omnivoice"
├── input: text (max 4096 chars)
├── voice: "ash" | "clone:profile_id" | "female, accent"
├── response_format: "mp3" | "wav" | "opus" | "flac" | "aac" | "pcm"
├── speed: 0.25-4.0
└── [OmniVoice-specific params]
    ├── guidance_scale: float
    ├── num_step: int (16-50)
    ├── t_shift: float
    └── ...

# Voice profiles
/v1/voices/profiles
├── POST   - Create profile (ref_audio + name)
├── GET    - List profiles
├── GET    /{id} - Get profile
├── PATCH  /{id} - Update profile
└── DELETE /{id} - Delete profile

# Multi-speaker script (NEW)
POST /v1/audio/script
├── segments: [{speaker, text, voice}]
├── output_format: "single_track" | "multi_track"
├── pause_between_speakers: float
└── response_format: "mp3" | "wav" | ...
```

---

## Voice Resolution Logic

```python
# File: omnivoice_server/services/inference.py

async def synthesize(request: SpeechRequest) -> AudioOutput:
    voice_id = request.voice

    # 1. Clone voice mode
    if voice_id.startswith("clone:"):
        profile_id = voice_id[6:]  # Remove "clone:" prefix
        profile = await profile_service.get(profile_id)
        return await model.clone(
            text=request.input,
            ref_audio=profile.ref_audio_path
        )

    # 2. Voice design mode
    elif "," in voice_id:
        # Parse "female, british accent, low pitch"
        attributes = parse_design_attributes(voice_id)
        return await model.design(
            text=request.input,
            instruct=format_instruct(attributes)
        )

    # 3. OpenAI preset mapping
    elif voice_id in VOICE_PRESETS:
        preset = VOICE_PRESETS[voice_id]
        return await model.design(
            text=request.input,
            instruct=preset.instruct
        )

    else:
        raise ValueError(f"Unknown voice: {voice_id}")
```

---

## OpenAI Preset Mappings

| Preset | OmniVoice Design Attributes |
|--------|----------------------------|
| `alloy` | `moderate, balanced` |
| `ash` | `male, warm, american accent` |
| `ballad` | `male, expressive, american accent` |
| `coral` | `female, friendly, american accent` |
| `echo` | `male, clear, american accent` |
| `fable` | `male, british accent, narrative` |
| `nova` | `female, professional, calm, american accent` |
| `onyx` | `male, deep, serious, american accent` |
| `sage` | `female, warm, trustworthy, american accent` |
| `shimmer` | `female, bright, energetic, american accent` |
| `verse` | `male, artistic, american accent` |

---

## Multi-Speaker Script API (NEW)

### Request Format

```json
{
  "script": [
    {"speaker": "alice", "voice": "clone:alice_profile", "text": "Hello!"},
    {"speaker": "bob", "voice": "design:male,deep", "text": "Hi Alice!"},
    {"speaker": "alice", "text": "How are you?"}
  ],
  "output_format": "single_track",
  "pause_between_speakers": 0.5,
  "response_format": "mp3"
}
```

### Response Format

```json
{
  "audio": "base64_encoded_audio",
  "format": "mp3",
  "duration_s": 12.34,
  "speakers": ["alice", "bob"],
  "metadata": {
    "segments": [...],
    "processing_time_ms": 1234
  }
}
```

---

## Known Issues & Limitations

### From Issue #21 Analysis

| Issue | Status | Root Cause | Priority |
|-------|--------|------------|----------|
| **Inconsistent voice** | 🔴 Open | OmniVoice random sampling | High |
| **Clone voice not working** | 🟡 Investigating | Integration issue? | High |
| **Weird noise artifacts** | 🟡 Investigating | Model/text preprocessing | Medium |
| **Wrong gender output** | 🟡 Investigating | Multi-speaker logic? | High |

### Documented Limitations

| Limitation | Description | Workaround |
|------------|-------------|------------|
| **MPS (Apple Silicon)** | Broken, use CPU | Set `device=cpu` |
| **CPU Performance** | RTF ~4.92 | Use GPU for production |
| **Streaming granularity** | Sentence-level, not word-level | Wait for update |
| **Batch API** | Not implemented | Sequential calls |

---

## Integration with Open Notebook / Podcastfy

### Data Flow

```
Open Notebook UI (Next.js)
    ↓ User configures speakers with Voice IDs
Podcastfy Backend (Python)
    ↓ Generates transcript with speaker tags
    ↓ For each segment:
        ├── Parse speaker → voice_id
        ├── Resolve voice (preset/clone/design)
        └── Call TTS API
OmniVoice-server (FastAPI)
    ↓ Process TTS request
OmniVoice Model (PyTorch)
    ↓ Generate audio
    ↓ Return audio data
Podcastfy
    ↓ Mix segments with pauses
    ↓ Export final podcast
Open Notebook
    ↓ Download/Play for user
```

### Potential Integration Issues

1. **Voice ID Format**
   - Open Notebook may not be sending the correct `clone:` prefix
   - Need to verify the format being transmitted

2. **Multi-speaker Consistency**
   - Podcastfy calls API for each segment individually
   - Each call is independent → voice variation

3. **Clone Voice Flow**
   - Step 1: Create profile (may already be done)
   - Step 2: Use `clone:profile_id` (may be failing)

---

## Configuration

### Environment Variables

```bash
# Server
OMNIVOICE_HOST=0.0.0.0
OMNIVOICE_PORT=8880
OMNIVOICE_WORKERS=1

# Model
OMNIVOICE_DEVICE=cuda  # or cpu, mps (broken)
OMNIVOICE_DTYPE=float16
OMNIVOICE_MODEL_PATH=k2-fsa/OmniVoice

# Features
OMNIVOICE_ENABLE_STREAMING=true
OMNIVOICE_MAX_TEXT_LENGTH=4096
OMNIVOICE_PROFILE_STORAGE_PATH=./profiles

# Auth (optional)
OMNIVOICE_API_KEY=sk-...
```

### Docker Deployment

```bash
# CPU version
docker run -p 8880:8880 maemreyo/omnivoice-server:latest

# CUDA version
docker run --gpus all -p 8880:8880 maemreyo/omnivoice-server:cuda
```

---

## Testing & Debugging

### Direct API Test

```bash
# Test 1: Basic synthesis
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"omnivoice","input":"Hello","voice":"ash"}' \
  --output test.mp3

# Test 2: Create profile
curl -X POST http://localhost:8880/v1/voices/profiles \
  -F "name=Test" \
  -F "audio_file=@reference.wav"

# Test 3: Clone voice
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "Testing clone voice",
    "voice": "clone:profile_id_from_step_2"
  }' \
  --output cloned.mp3

# Test 4: Multi-speaker script
curl -X POST http://localhost:8880/v1/audio/script \
  -H "Content-Type: application/json" \
  -d '{
    "script": [
      {"speaker": "A", "voice": "ash", "text": "Hello"},
      {"speaker": "B", "voice": "nova", "text": "Hi there"}
    ],
    "output_format": "single_track"
  }' \
  --output dialogue.mp3
```

### Python Client Test

```python
from openai import OpenAI

client = OpenAI(
    api_key="dummy",
    base_url="http://localhost:8880/v1"
)

# Test basic synthesis
response = client.audio.speech.create(
    model="omnivoice",
    voice="ash",
    input="Hello world"
)
with open("test.mp3", "wb") as f:
    f.write(response.content)

# Test with extra params
response = client.audio.speech.create(
    model="omnivoice",
    voice="female, british accent",
    input="Custom voice design",
    extra_body={"speed": 1.2, "guidance_scale": 3.0}
)
```

---

## Performance Benchmarks

| Configuration | RTF | Real-time Factor |
|--------------|-----|------------------|
| CPU (Intel/AMD) | ~4.92 | 5x slower |
| CUDA (RTX 4090) | ~0.2 | 5x faster |
| CUDA (A100) | ~0.025 | 40x faster |
| MPS (Apple M1/M2) | Broken | Use CPU |

---

## Roadmap

### Phase 1 (Current Priority)
- [ ] Fix voice consistency issues
- [ ] Investigate clone voice integration
- [ ] Improve streaming granularity

### Phase 2
- [ ] Batch inference API
- [ ] Word-level streaming
- [ ] Enhanced caching layer

### Phase 3
- [ ] SSML support
- [ ] Emotion presets
- [ ] Voice blending/interpolation

---

## Recommendations for Issue #21

### Immediate Actions

1. **Add Debug Logging**
   ```python
   # Log all incoming requests with full body
   # Log voice resolution steps
   # Log model parameters
   ```

2. **Verify Open Notebook Integration**
   - Capture actual HTTP requests from Open Notebook
   - Check voice ID format being sent
   - Verify clone: prefix handling

3. **Add Seed Control**
   ```python
   # Allow reproducible generation
   synthesize(..., seed=42)
   ```

4. **Test Multi-speaker Script API**
   - Open Notebook should possibly use `/v1/audio/script`
   - Instead of calling individual synthesis for each segment

### Long-term Improvements

1. **Semantic Caching**: Cache audio for common phrases
2. **Voice Embedding Persistence**: Cache speaker embeddings
3. **Batch API**: For large-scale synthesis

---

## Related Technologies

- **OmniVoice**: Core TTS model (k2-fsa/OmniVoice)
- **FastAPI**: Web framework used by OmniVoice-server
- **OpenAI API**: Compatible API format
- **Podcastfy**: Library using TTS in Open Notebook

---

## Conclusion

OmniVoice-server provides a solid foundation for TTS with an OpenAI-compatible API. However, issue #21 shows there may be integration challenges with Open Notebook/Podcastfy:

1. **Voice consistency**: Need seed control or voice embedding caching
2. **Clone voice**: Need to verify integration flow is correct
3. **Multi-speaker**: May need to use script API instead of individual calls

To fully resolve the issue, need:
- Close collaboration with Open Notebook team
- Detailed integration testing
- May need additional features (seed control, better logging)

---

*Report generated for issue #21 investigation*