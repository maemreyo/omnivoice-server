## API Reference

### Endpoints

#### `POST /v1/audio/speech`

Generate speech from text (OpenAI-compatible).

**Request body:**
```json
{
  "model": "omnivoice",
  "input": "Text to synthesize",
  "voice": "alloy",
  "speaker": "onyx",
  "instructions": "female,british accent",
  "response_format": "wav",
  "speed": 1.0,
  "stream": false,
  "stream_format": "sse",
  "reference_text": "Optional compatibility alias for ref_text",
  "voice_url": "https://example.com/reference.wav",
  "chunk_size": 8,
  "num_step": 32,
  "guidance_scale": 3.0,
  "denoise": true,
  "t_shift": 0.1,
  "position_temperature": 5.0,
  "class_temperature": 0.0,
  "duration": 3.5,
  "layer_penalty_factor": 0.5,
  "preprocess_prompt": true,
  "postprocess_output": true,
  "audio_chunk_duration": 0.5,
  "audio_chunk_threshold": 0.1
}
```

**Parameter precedence**:
- `instructions` (strongest, upstream voice design)
- `speaker` preset (server-only mapping)
- `voice` preset (server-only mapping)
- server default prompt

**Response:** Audio file (WAV or PCM)

`stream_format: "sse"` returns `text/event-stream` events compatible with the
faster-qwen3-tts server. Each `audio.chunk` event contains base64 audio data,
followed by a `done` event and `data: [DONE]`. Streaming `pcm` returns raw PCM;
streaming `wav` begins with an unknown-length WAV header.

#### `POST /v1/audio/speech/clone`

One-shot voice cloning (multipart form).

**Form fields:**
- `text` (required): Text to synthesize
- `ref_audio` (required): Reference audio file
- `ref_text` (optional): Reference transcript
- `speed` (optional): Playback speed (default: 1.0)
- `num_step` (optional): Inference steps
- `guidance_scale` (optional): CFG scale
- `denoise` (optional): Enable denoising
- `t_shift` (optional): Noise schedule shift
- `position_temperature` (optional): Voice diversity
- `class_temperature` (optional): Token sampling temperature
- `duration` (optional): Fixed output duration
- `layer_penalty_factor` (optional): Layer penalty factor
- `preprocess_prompt` (optional): Enable prompt preprocessing
- `postprocess_output` (optional): Enable output postprocessing
- `audio_chunk_duration` (optional): Audio chunk duration
- `audio_chunk_threshold` (optional): Audio chunk threshold

**Response:** Audio file (WAV)

#### `GET /v1/voices`

List available voices and profiles.

**Response:**
```json
{
  "voices": [
    {
      "id": "design:<attributes>",
      "type": "design",
      "description": "Custom voice design using upstream OmniVoice attributes"
    },
    {
      "id": "alloy",
      "type": "preset",
      "description": "Server-only preset mapped to: female, young adult, moderate pitch, american accent"
    },
    {
      "id": "clone:my_voice",
      "type": "clone",
      "profile_id": "my_voice",
      "description": "Server-stored voice profile (use /v1/audio/speech/clone for synthesis)"
    }
  ],
  "design_attributes": {
    "gender": ["male", "female"],
    "age": ["child", "teenager", "young adult", "middle-aged", "elderly"],
    "pitch": ["very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"],
    "style": ["whisper"],
    "accent_en": ["american accent", "british accent", "australian accent", ...],
    "dialect_zh": ["河南话", "陕西话", "四川话", ...]
  },
  "total": 3
}
```

### faster-qwen3-tts compatibility endpoints

The following aliases are provided for clients written against the local
`faster-qwen3-tts` OpenAI server:

- `GET /v1/audio/models` — alias for `/v1/models`.
- `GET /v1/audio/voices` — OpenAI-style `{object: "list", data: [...]}` voice list.
- `GET /v1/audio/voices/{voice_id}` — retrieve a preset or stored profile.
- `PATCH /v1/audio/voices/{voice_id}` — update stored voice `name` and `ref_text`.
- `DELETE /v1/audio/voices/{voice_id}` — delete a stored voice profile.
- `POST /upload_voice` and `POST /v1/upload_voice` — upload a reference voice.

`/upload_voice` accepts `voice_file`, `voice_url`, `name` (or `voice_name`),
`ref_text` (or `reference_text`), and an optional JSON `data` form field. It
returns a generated `voice_id`. Uploaded voices can be selected in speech
requests by either their ID or display name.

For server-side URL imports, `voice_url` is restricted to public HTTP(S)
addresses by default. Private and loopback addresses can be enabled for trusted
networks with `--allow-private-voice-urls` or
`OMNIVOICE_ALLOW_PRIVATE_VOICE_URLS=true`. Do not enable this for untrusted API
clients because it permits access to services on the server's local network.

The speech endpoint also accepts `ref_text`, `reference_text`, `voice_url`,
`stream_format`, and `chunk_size` request fields used by faster-qwen3-tts.
`chunk_size` is accepted for client compatibility; OmniVoice continues to use
its own `num_step` and audio chunk controls.

#### `POST /v1/voices/profiles`

Create a voice cloning profile (server-only storage feature).

**Form fields:**
- `profile_id` (required): Unique identifier (alphanumeric, dashes, underscores)
- `ref_audio` (required): Reference audio file
- `ref_text` (optional): Reference transcript
- `overwrite` (optional): Overwrite existing profile (default: false)

**Response:**
```json
{
  "profile_id": "my_voice",
  "created_at": "2026-04-04T12:00:00Z",
  "ref_text": "Reference text"
}
```

**Note**: Profiles are stored for management and inspection. For synthesis, use `POST /v1/audio/speech/clone` with reference audio.

#### `GET /v1/voices/profiles/{profile_id}`

Get profile details (server-only storage feature).

#### `PATCH /v1/voices/profiles/{profile_id}`

Update profile ref_audio and/or ref_text (server-only storage feature).

#### `DELETE /v1/voices/profiles/{profile_id}`

Delete a profile (server-only storage feature).

#### `GET /v1/models`

List available models (OpenAI-compatible).

#### `GET /health`

Health check endpoint.

#### `GET /metrics`

Prometheus-style metrics.
