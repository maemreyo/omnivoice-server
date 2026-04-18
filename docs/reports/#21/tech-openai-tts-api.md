# OpenAI TTS API - Tech Report

> **Issue Reference**: [#21 - Voice Quality Issues for Podcast Output](https://github.com/maemreyo/omnivoice-server/issues/21)  
> **Research Date**: 2026-04-18  
> **Documentation**: [platform.openai.com/docs/guides/text-to-speech](https://platform.openai.com/docs/guides/text-to-speech)  
> **API Reference**: [platform.openai.com/docs/api-reference/audio](https://platform.openai.com/docs/api-reference/audio)

---

## Overview

**OpenAI Text-to-Speech API** is OpenAI's TTS service, providing 13 built-in voices with natural quality. OmniVoice-server implements an OpenAI-compatible API to allow drop-in replacement for OpenAI TTS.

---

## API Specification

### Endpoint

```
POST https://api.openai.com/v1/audio/speech
```

### Request Body

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `model` | string | Yes | Model ID: `tts-1` or `tts-1-hd` |
| `input` | string | Yes | Text to synthesize (max 4096 chars) |
| `voice` | string | Yes | Voice ID (alloy, echo, fable, etc.) |
| `response_format` | string | No | `mp3`, `opus`, `aac`, `flac`, `wav`, `pcm` (default: mp3) |
| `speed` | float | No | 0.25 to 4.0 (default: 1.0) |

### Response

- **Content-Type**: `audio/mpeg`, `audio/wav`, etc.
- **Body**: Binary audio data

---

## OpenAI Voices (13 Presets)

| Voice | Gender | Character |
|-------|--------|-----------|
| `alloy` | Neutral | Balanced, versatile |
| `ash` | Male | Warm, professional |
| `ballad` | Male | Expressive, storytelling |
| `coral` | Female | Friendly, approachable |
| `echo` | Male | Clear, authoritative |
| `fable` | Neutral | British accent, narrative |
| `nova` | Female | Professional, calm |
| `onyx` | Male | Deep, serious |
| `sage` | Female | Warm, trustworthy |
| `shimmer` | Female | Bright, energetic |
| `verse` | Neutral | Poetic, artistic |

---

## OmniVoice-server Compatibility

### API Mapping

| OpenAI Feature | OmniVoice-server Support | Notes |
|----------------|-------------------------|-------|
| `POST /v1/audio/speech` | ✅ Full | Core endpoint |
| `model` param | ✅ Mapped to OmniVoice | Only `omnivoice` supported |
| `input` param | ✅ Full | Pass through to model |
| `voice` param | ✅ Extended | OpenAI presets + design attributes + clone |
| `response_format` | ✅ Full | mp3, wav, opus, flac, aac, pcm |
| `speed` param | ✅ Full | 0.25-4.0 range |
| Streaming | ✅ Partial | Sentence-level (not word-level) |
| Voices endpoint | ✅ Extended | `/v1/voices` with more info |

### Extended Features (Beyond OpenAI)

OmniVoice-server adds capabilities not available in the OpenAI API:

| Feature | Endpoint | Description |
|---------|----------|-------------|
| **Voice Cloning** | `POST /v1/audio/speech` | `voice: "clone:profile_id"` |
| **Voice Design** | `POST /v1/audio/speech` | `voice: "female, british accent"` |
| **Voice Profiles** | `POST /v1/voices/profiles` | Persistent voice storage |
| **Multi-speaker** | `POST /v1/audio/script` | Generate dialogue with multiple voices |
| **Advanced params** | `POST /v1/audio/speech` | `guidance_scale`, `num_step`, etc. |

---

## Request Examples

### Basic Request (OpenAI-style)

```bash
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "Hello, this is a test.",
    "voice": "ash",
    "response_format": "mp3"
  }' \
  --output speech.mp3
```

### Voice Cloning

```bash
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "Hello using cloned voice",
    "voice": "clone:profile_abc123"
  }'
```

### Voice Design

```bash
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "Hello with custom voice",
    "voice": "female, british accent, low pitch"
  }'
```

### Advanced Parameters

```bash
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "High quality speech",
    "voice": "alloy",
    "guidance_scale": 3.0,
    "num_step": 32,
    "speed": 1.2
  }'
```

---

## Voice ID Resolution Logic

OmniVoice-server parses the `voice` parameter in the following order:

```python
def resolve_voice(voice: str) -> VoiceConfig:
    if voice.startswith("clone:"):
        # Voice cloning mode
        profile_id = voice[6:]  # Remove "clone:" prefix
        return load_clone_voice(profile_id)

    elif "," in voice:
        # Voice design mode
        # e.g., "female, british accent"
        return parse_design_attributes(voice)

    elif voice in OPENAI_PRESETS:
        # OpenAI preset mapping
        return OPENAI_PRESET_MAP[voice]

    else:
        raise ValueError(f"Unknown voice: {voice}")
```

---

## Compatibility with Open Notebook / Podcastfy

### Expected Behavior

Open Notebook/Podcastfy expects OpenAI-compatible API:

```python
# Podcastfy's OpenAI TTS client
import openai

client = openai.OpenAI(
    api_key="sk-...",
    base_url="http://localhost:8880/v1"  # OmniVoice-server
)

response = client.audio.speech.create(
    model="omnivoice",
    voice="ash",  # or "clone:profile_id"
    input="Hello world"
)
```

### Potential Issues (from Issue #21)

| Issue | Hypothesis | Verification |
|-------|------------|--------------|
| Clone voice not working | `clone:` prefix not parsed | Test direct API call |
| Wrong voice output | Voice ID mismatch | Check preset mapping |
| Inconsistent voice | No seed control | Verify random behavior |

---

## OpenAI vs OmniVoice-server Comparison

| Feature | OpenAI TTS | OmniVoice-server |
|---------|------------|------------------|
| **Pricing** | Pay per character | Free (self-hosted) |
| **Voice Cloning** | ❌ No | ✅ Yes |
| **Voice Design** | ❌ No | ✅ Yes (gender, accent, etc.) |
| **Languages** | ~30 | 600+ |
| **Speed Control** | ✅ Yes | ✅ Yes |
| **Custom Voice** | ❌ No | ✅ Via cloning |
| **Data Privacy** | Cloud | On-premise |
| **Quality** | High | High (comparable) |
| **Inference Speed** | Fast | Fast on GPU |

---

## Streaming API

### OpenAI Format

```python
response = client.audio.speech.create(
    model="tts-1",
    voice="alloy",
    input="Hello",
    stream=True  # If supported
)
```

### OmniVoice-server Streaming

```bash
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "Long text for streaming...",
    "voice": "ash",
    "stream": true
  }' \
  --output - | player
```

**Note**: OmniVoice-server currently supports sentence-level streaming (not true chunk streaming like OpenAI's realtime API).

---

## Error Handling

### OpenAI Error Format

```json
{
  "error": {
    "message": "Error description",
    "type": "invalid_request_error",
    "param": "voice",
    "code": "voice_not_found"
  }
}
```

### OmniVoice-server Error Mapping

| OmniVoice Error | HTTP Status | OpenAI-style Response |
|-----------------|-------------|----------------------|
| Invalid voice | 400 | `invalid_request_error` |
| Profile not found | 404 | `voice_not_found` |
| Model error | 500 | `api_error` |
| Rate limit | 429 | `rate_limit_exceeded` |

---

## Connection to Issue #21

### Debugging Steps

1. **Verify OpenAI API Compatibility**
   ```bash
   # Test with curl
   curl http://localhost:8880/v1/audio/speech \
     -H "Content-Type: application/json" \
     -d '{"model":"omnivoice","input":"test","voice":"ash"}'

   # Test with OpenAI Python client
   python -c "
   import openai
   client = openai.OpenAI(base_url='http://localhost:8880/v1', api_key='dummy')
   response = client.audio.speech.create(model='omnivoice', voice='ash', input='test')
   print('Success:', len(response.content))
   "
   ```

2. **Check Voice ID Handling**
   - Confirm `clone:` prefix is parsed correctly
   - Verify OpenAI preset mapping

3. **Test Advanced Parameters**
   - Check if Podcastfy/Open Notebook sends extra params
   - Verify OmniVoice-server handles params correctly

---

## Recommendations

### For Issue #21 Investigation

1. **Log All Requests**
   ```python
   # Add logging middleware
   @app.middleware("http")
   async def log_requests(request, call_next):
       body = await request.body()
       logger.info(f"Request: {body}")
       response = await call_next(request)
       return response
   ```

2. **Add Compatibility Mode**
   - Strict OpenAI compatibility mode (ignore OmniVoice-specific params)
   - Debug mode (verbose logging)

3. **Document Voice ID Format**
   - Clear documentation for `clone:` prefix
   - Examples for design attributes

---

## Related Technologies

- **OmniVoice-server**: OpenAI-compatible server implementation
- **OpenAI Python SDK**: Client library using OpenAI API
- **Podcastfy**: Uses OpenAI TTS client
- **Open Notebook**: Frontend calling TTS via Podcastfy

---

## Conclusion

OmniVoice-server implements an OpenAI-compatible API allowing integration with tools like Podcastfy and Open Notebook. Issues in issue #21 may be related to:

1. **Voice ID parsing**: `clone:` prefix handling
2. **API compatibility**: Response format mismatch
3. **Parameter handling**: Extra params from Podcastfy

To investigate, need:
- Log and analyze actual API calls from Open Notebook
- Test directly with OpenAI client
- Verify all endpoints work correctly

---

*Report generated for issue #21 investigation*