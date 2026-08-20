# Podcastfy - Tech Report

> **Issue Reference**: [#21 - Voice Quality Issues for Podcast Output](https://github.com/maemreyo/omnivoice-server/issues/21)  
> **Research Date**: 2026-04-18  
> **GitHub**: [souzatharsis/podcastfy](https://github.com/souzatharsis/podcastfy)  
> **PyPI**: [podcastfy](https://pypi.org/project/podcastfy/)  
> **Docs**: [podcastfy.readthedocs.io](https://podcastfy.readthedocs.io/)

---

## Overview

**Podcastfy** is an open-source Python library that converts multimodal content into multilingual AI-generated audio conversation segments using GenAI. This is an alternative to Google NotebookLM's podcast feature.

---

## Key Characteristics

| Aspect | Details |
|--------|---------|
| **License** | Apache 2.0 |
| **Language** | Python 3.9+ |
| **Architecture** | Modular, CLI + Python API + Web App |
| **TTS Support** | OpenAI, Google, ElevenLabs, Microsoft Edge |
| **LLM Support** | 100+ models (OpenAI, Anthropic, Google, Local) |
| **Input Types** | Text, Images, PDFs, Websites, YouTube |

---

## Architecture

```
Podcastfy Core
├── Content Processing Layer
│   ├── PDF Extractor
│   ├── Website Scraper
│   ├── YouTube Transcript
│   ├── Image Analyzer (Vision LLM)
│   └── Raw Text Handler
├── Transcript Generation Layer
│   ├── LLM Client (OpenAI, Anthropic, etc.)
│   ├── Conversation Prompt Engineering
│   └── Multi-speaker Dialogue Generator
└── Audio Generation Layer
    ├── TTS Provider Abstraction
    │   ├── OpenAI TTS Client
    │   ├── Google TTS Client
    │   ├── ElevenLabs Client
    │   └── Microsoft Edge TTS
    ├── Audio Mixer
    │   ├── Segment Concatenation
    │   ├── Pause Insertion
    │   └── Volume Normalization
    └── Output Formatter
        ├── MP3/WAV Export
        └── Metadata Tagging
```

---

## TTS Provider Integration

### Supported TTS Models

| Provider | Models | Voice Cloning | Multi-language |
|----------|--------|---------------|----------------|
| **OpenAI** | tts-1, tts-1-hd | ❌ No | ✅ Yes |
| **Google** | Gemini TTS | ⚠️ Limited | ✅ Yes |
| **ElevenLabs** | Multilingual v2 | ✅ Yes | ✅ Yes |
| **Microsoft** | Edge TTS | ❌ No | ✅ Yes |

### OmniVoice-server as Custom Provider

Podcastfy does not currently have native support for OmniVoice-server, but can be integrated via:

1. **OpenAI-compatible endpoint**: Use `/v1/audio/speech`
2. **Custom TTS client**: Extend base class

---

## Integration with Open Notebook

Open Notebook uses Podcastfy as the core library for podcast generation:

```
Open Notebook (Next.js Frontend)
    ↓ API calls
Podcastfy Python Backend
    ↓ TTS API calls
OmniVoice-server / OpenAI / ElevenLabs
```

### Configuration Flow

```python
# Simplified podcastfy configuration
config = {
    "conversation": {
        "style": "podcast",
        "language": "en",
        "speakers": [
            {"name": "Host", "voice": "ash"},
            {"name": "Guest", "voice": "nova"}
        ]
    },
    "tts": {
        "provider": "openai",  # Could be "omnivoice" if supported
        "model": "tts-1"
    }
}
```

---

## Audio Processing Pipeline

### Workflow

```
1. Input Content
   └── Parse to raw text

2. Generate Transcript
   └── LLM creates dialogue with speaker tags

   Example output:
   Host: Welcome to our podcast!
   Guest: Thanks for having me.
   Host: Let's discuss AI...

3. Split by Speaker
   └── Parse transcript into segments

4. Synthesize Each Segment
   └── Call TTS for each speaker segment

   For segment in segments:
       audio = tts.synthesize(
           text=segment.text,
           voice=segment.speaker.voice_id
       )

5. Mix Audio
   └── Concatenate with pauses
   └── Normalize volume
   └── Export to MP3
```

---

## Voice ID Handling

### Format Support

Podcastfy supports the following voice ID formats:

| Format | Example | Description |
|--------|---------|-------------|
| **OpenAI Preset** | `alloy`, `nova`, `shimmer` | Built-in OpenAI voices |
| **ElevenLabs** | `voice_id` | ElevenLabs voice ID |
| **Custom** | `clone:profile_id` | Voice cloning (provider-specific) |

### Potential Issue with OmniVoice-server

According to issue #21, users report:
- The `clone:` prefix may not be handled correctly
- Multi-speaker with male/female voices both output male voice

**Hypothesis**: Podcastfy or Open Notebook may:
1. Not be passing the `clone:` prefix correctly
2. Be falling back to default voice
3. Not support OmniVoice design attributes (`female, british accent`)

---

## Configuration Options

### conversation_custom.md

```yaml
# Podcast customization
output_language: "en"
podcast_name: "Tech Talk"
podcast_tagline: "AI and Technology"
conversation_style: ["engaging", "natural"]
engagement_techniques: ["questions", "examples"]
dialogue_structure: ["introduction", "main_content", "conclusion"]
```

### config.md

```yaml
# TTS Configuration
tts:
  provider: "openai"  # or "elevenlabs", "google", "edge"
  model: "tts-1-hd"
  voices:
    host: "ash"
    guest: "nova"

# LLM Configuration
llm:
  provider: "openai"
  model: "gpt-4"
```

---

## Integration Challenges with OmniVoice-server

### 1. API Compatibility

Podcastfy expects OpenAI-style response:
```python
# OpenAI response
response = openai.audio.speech.create(...)
audio = response.content  # Raw bytes
```

OmniVoice-server needs to ensure compatible response format.

### 2. Voice Design Attributes

OmniVoice supports design attributes:
```
female, british accent, low pitch
```

Podcastfy may not support this format, only preset names.

### 3. Clone Voice Flow

Podcastfy workflow for clone voice:
1. User provides reference audio
2. System creates voice profile
3. Use profile ID in subsequent calls

OmniVoice-server needs:
1. `POST /v1/voices/profiles` - Create profile
2. `GET /v1/voices/profiles/{id}/ref-audio` - Get reference path
3. Use in `speech` endpoint

---

## Recommendations

### For OmniVoice-server Compatibility

1. **Verify OpenAI API Compatibility**
   - Test with Podcastfy's OpenAI client
   - Ensure correct response format

2. **Document Voice ID Format**
   - Guide on how to use `clone:` prefix
   - Document design attributes support

3. **Consider Podcastfy Integration**
   - Write custom TTS provider for Podcastfy
   - Submit PR to support OmniVoice-server natively

### For Open Notebook Users

1. **Check Voice Configuration**
   ```
   Speaker Profile → Voice ID
   - Use preset: "ash", "alloy", "nova"
   - Or clone: "clone:profile_id" (if supported)
   ```

2. **Test Direct API**
   - Test OmniVoice-server API first to isolate the issue

3. **Workaround**
   - Use Voice Design presets instead of clone
   - Configure design attributes in OmniVoice-server

---

## Related Technologies

- **Open Notebook**: Frontend/UI using Podcastfy
- **OmniVoice-server**: HTTP server for TTS
- **OpenAI TTS**: Reference API implementation
- **NotebookLM**: Google tool that Podcastfy replaces

---

## Conclusion

Podcastfy is a powerful library for podcast generation, currently used by Open Notebook. However, integration with OmniVoice-server may have issues due to:

1. No native support for OmniVoice-server
2. Possible mismatch in voice ID handling
3. Clone voice flow not yet tested with OmniVoice-server

To resolve issue #21:
- Verify Podcastfy/Open Notebook is sending correct API calls
- Check voice ID parsing logic
- Test direct OmniVoice-server API to isolate the issue

---

*Report generated for issue #21 investigation*