## API Usage

### Basic Synthesis

```python
import httpx

response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "model": "omnivoice",
        "input": "Hello world!",
        "response_format": "wav"
    }
)

with open("output.wav", "wb") as f:
    f.write(response.content)
```

### Voice Design

Specify voice attributes to design a custom voice:

```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "model": "omnivoice",
        "input": "This voice has specific attributes.",
        "instructions": "female,british accent,young adult,high pitch"
    }
)
```

`instructions` is the strongest control and overrides preset selection. If `instructions`
is absent, `/v1/audio/speech` also accepts OpenAI-style preset names in `voice` or
`speaker`, such as `alloy`, `nova`, `onyx`, and `shimmer`. Unknown values are ignored,
and the server falls back to the default design prompt `male, middle-aged, moderate pitch, british accent`.

**Canonical instruction vocabulary** (upstream OmniVoice attributes):
- **Gender**: `male`, `female`
- **Age**: `child`, `teenager`, `young adult`, `middle-aged`, `elderly`
- **Pitch**: `very low pitch`, `low pitch`, `moderate pitch`, `high pitch`, `very high pitch`
- **Style**: `whisper`
- **Accent (English)**: `american accent`, `british accent`, `australian accent`, `chinese accent`, `canadian accent`, `indian accent`, `korean accent`, `portuguese accent`, `russian accent`, `japanese accent`
- **Dialect (Chinese)**: `河南话`, `陕西话`, `四川话`, `贵州话`, `云南话`, `桂林话`, `济南话`, `石家庄话`, `甘肃话`, `宁夏话`, `青岛话`, `东北话`

**Note**: Short accent aliases like `british`, `american` are accepted but canonicalized internally to full forms like `british accent`.

**OpenAI-compatible presets** (server-only convenience mappings):
- `alloy`, `ash`, `ballad`, `cedar`, `coral`, `echo`, `fable`, `marin`, `nova`, `onyx`, `sage`, `shimmer`, `verse`

Preset mapping table:

| Preset | Local design prompt |
|--------|---------------------|
| `alloy` | `female, young adult, moderate pitch, american accent` |
| `ash` | `male, young adult, low pitch, american accent` |
| `ballad` | `male, middle-aged, low pitch, british accent` |
| `cedar` | `male, middle-aged, low pitch, american accent` |
| `coral` | `female, young adult, high pitch, australian accent` |
| `echo` | `male, middle-aged, moderate pitch, canadian accent` |
| `fable` | `female, middle-aged, moderate pitch, british accent` |
| `marin` | `female, middle-aged, moderate pitch, canadian accent` |
| `nova` | `female, young adult, high pitch, american accent` |
| `onyx` | `male, middle-aged, very low pitch, british accent` |
| `sage` | `female, elderly, low pitch, british accent` |
| `shimmer` | `female, young adult, very high pitch, american accent` |
| `verse` | `male, young adult, moderate pitch, british accent` |

### Voice Cloning

#### Option 1: Save a Profile (Reusable)

```python
# Create a profile
with open("reference.wav", "rb") as f:
    response = httpx.post(
        "http://127.0.0.1:8880/v1/voices/profiles",
        data={
            "profile_id": "my_voice",
            "ref_text": "This is the reference text."
        },
        files={"ref_audio": f}
    )

# Profiles are stored for management and inspection.
# For synthesis, use POST /v1/audio/speech/clone with reference audio.
```

#### Option 2: One-Shot Cloning

```python
with open("reference.wav", "rb") as f:
    response = httpx.post(
        "http://127.0.0.1:8880/v1/audio/speech/clone",
        data={
            "text": "This is one-shot cloning.",
            "ref_text": "Reference text."
        },
        files={"ref_audio": f}
    )
```

### Streaming

Stream audio in real-time for lower latency:

```python
with httpx.stream(
    "POST",
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "model": "omnivoice",
        "input": "Long text to stream...",
        "stream": True
    }
) as response:
    for chunk in response.iter_bytes():
        # Process PCM audio chunks
        play_audio(chunk)
```

See `examples/streaming_player.py` for a complete example.
