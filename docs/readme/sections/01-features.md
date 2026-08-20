## Features

### Upstream OmniVoice Capabilities (Pass-Through)

omnivoice-server forwards these features directly to the upstream OmniVoice model:

- **Voice design attributes** - Control gender, age, pitch, accent, dialect, and whisper style
- **Voice cloning** - Clone voices from reference audio samples
- **Non-verbal expressions** - Inline symbols like `[laughter]`, `[breath]`, `[sigh]`, `[sniff]`
- **Pronunciation control** - Pinyin hints for Chinese, CMU dictionary format for English
- **Generation parameters** - Fine-tune quality with `num_step`, `guidance_scale`, `temperature`, `denoise`, and more
- **Speed control** - 0.25x to 4.0x playback speed
- **Multiple languages** - English, Chinese, and other languages supported by OmniVoice

### Server-Only Extensions

omnivoice-server adds these wrapper features on top of OmniVoice:

- **OpenAI-compatible REST API** - Drop-in replacement for OpenAI TTS endpoints
- **HTTP streaming transport** - Sentence-level chunked transfer for lower perceived latency
- **Voice profile storage** - Persistent filesystem storage for cloned voice references (CRUD operations)
- **OpenAI preset mappings** - Convenience aliases (`alloy`, `nova`, `onyx`, etc.) mapped to design prompts
- **Bearer token authentication** - Optional API key protection
- **Concurrent request handling** - Configurable thread pool for parallel synthesis
- **Audio format conversion** - Tensor to WAV/PCM byte conversion
- **Production features** - Health checks, Prometheus metrics, request timeouts
