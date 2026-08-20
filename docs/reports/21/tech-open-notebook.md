# Open Notebook - Tech Report

> **Issue Reference**: [#21 - Voice Quality Issues for Podcast Output](https://github.com/maemreyo/omnivoice-server/issues/21)  
> **Research Date**: 2026-04-18  
> **Website**: [open-notebook.ai](https://www.open-notebook.ai/)  
> **GitHub**: [lfnovo/open-notebook](https://github.com/lfnovo/open-notebook)

---

## Overview

**Open Notebook** is an open-source AI tool that allows users to create podcasts from their own data. This is an alternative to Google NotebookLM with a focus on privacy and customization.

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Podcast Generator** | Convert content into conversational podcasts between AI speakers |
| **Custom Templates** | Create custom speaker names, taglines, and roles |
| **Multi-language** | Support multiple languages for podcast |
| **Voice Selection** | Integration with multiple TTS providers (OpenAI, Gemini, ElevenLabs) |
| **Speaker Profiles** | Define speakers with Voice ID (including voice cloning) |
| **Content Integration** | Use user notes and assets as context |

---

## Architecture & Dependencies

```
Open Notebook
├── Podcast Generator (powered by Podcastfy)
│   ├── TTS Providers
│   │   ├── OpenAI TTS API
│   │   ├── Google Gemini TTS
│   │   ├── ElevenLabs
│   │   └── Microsoft Edge TTS
│   ├── LLM for Transcript
│   │   ├── OpenAI GPT
│   │   ├── Anthropic Claude
│   │   ├── Google Gemini
│   │   └── Local LLMs (156+ HuggingFace models)
│   └── Content Processors
│       ├── PDF Parser
│       ├── YouTube Transcript
│       ├── Website Scraper
│       └── Image Analysis
└── Web Interface (Next.js/React)
```

---

## TTS Integration

### OmniVoice-server Integration

Open Notebook supports integration with OmniVoice-server through:

- **Voice ID Format**: `clone:profile_id` or preset voices (ash, alloy, nova, etc.)
- **Speaker Profiles**: Create profile ID from reference audio, then use in Voice ID
- **API Endpoint**: `/v1/audio/speech` (OpenAI-compatible)

### Issues Reported in Issue #21

| Issue | Description | Root Cause Hypothesis |
|-------|-------------|----------------------|
| **Voice Quality Drop** | Noisy voice (non-human voice) at 5m19s | Possible cause: model or text preprocessing |
| **Inconsistent Voice** | Each transcript has different voice | OmniVoice model uses random seed |
| **Clone Voice Not Working** | Output does not match reference audio | Possible causes: 1) Open Notebook does not support clone mode yet or 2) `clone:` prefix processing error |
| **Wrong Gender Voice** | 2 speakers (male/female) but both produce male voice | Possible bug in Open Notebook or OmniVoice-server |

---

## Voice ID Format in Open Notebook

According to Open Notebook documentation, users enter Voice ID in Speaker Profile:

```
Speaker Profile Configuration:
├── Name: "Speaker 1"
├── Role: "Host"
└── Voice ID: "clone:profile_abc123"  # or "ash", "alloy", "nova", ...
```

### Supported Preset Voices

- OpenAI presets: `alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `onyx`, `nova`, `sage`, `shimmer`, `verse`
- OmniVoice-specific: Design attributes like `female, british accent`, `male, deep`, etc.

---

## Podcast Workflow

```
1. User Input
   ├── Upload documents/PDFs/URLs
   ├── Define podcast template
   └── Configure speakers with Voice IDs

2. Content Generation (LLM)
   └── Generate conversational transcript

3. Audio Generation (TTS)
   └── For each speaker segment:
       ├── Resolve voice (preset/clone/design)
       ├── Call TTS API
       └── Collect audio segments

4. Assembly (Podcastfy)
   ├── Mix segments with pauses
   └── Export final podcast file
```

---

## Integration Points with OmniVoice-server

### API Endpoints Used

| Endpoint | Purpose | Compatibility |
|----------|---------|---------------|
| `POST /v1/audio/speech` | Single voice synthesis | ✅ Full |
| `POST /v1/audio/speech/clone` | One-shot cloning | ⚠️ Partial |
| `GET /v1/voices` | List available voices | ✅ Full |
| `GET /v1/voices/profiles/{id}` | Get profile details | ✅ Full |
| `POST /v1/voices/profiles` | Create voice profile | ✅ Full |
| `POST /v1/audio/script` | Multi-speaker script | ⚠️ Unknown |

### Potential Issues

1. **Clone Voice Mode**: Open Notebook may not have correctly integrated `clone:` prefix
2. **Multi-speaker Logic**: May be merging segments or not passing correct voice ID
3. **Gender Consistency**: May not be applying design attributes correctly

---

## Recommendations for Debugging

### 1. Verify Clone Voice Flow

```bash
# Test 1: Direct API call to verify clone works
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "Hello world",
    "voice": "clone:profile_abc123"
  }'

# Test 2: Create profile first
curl -X POST http://localhost:8880/v1/voices/profiles \
  -F "name=Test Speaker" \
  -F "audio_file=@reference.wav"
```

### 2. Check Open Notebook Configuration

- Confirm Open Notebook is sending correct format `clone:profile_id`
- Check logs to see if voice ID is being parsed correctly
- Verify Open Notebook supports multi-speaker with clone voices

### 3. Test Workaround

If Open Notebook does not support clone mode yet:
- Use Voice Design as alternative (e.g., `female, american accent`)
- Pre-clone voice and use preset voice mapping

---

## Related Technologies

- **Podcastfy**: Python library for podcast generation (core of Open Notebook)
- **OmniVoice-server**: HTTP server wrapper for OmniVoice TTS
- **OmniVoice**: TTS model from k2-fsa

---

## Conclusion

Open Notebook is a powerful tool for podcast generation but may encounter compatibility issues with OmniVoice-server when using clone voice mode. Further investigation is needed into how Open Notebook parses and passes voice ID to determine the root cause.

---

*Report generated for issue #21 investigation*