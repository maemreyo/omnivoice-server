## Advanced Features

### Non-Verbal Symbols

OmniVoice natively supports non-verbal symbols inline in text (upstream pass-through feature):

```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "input": "Hello [laughter] this is amazing [breath] really cool [sigh]"
    }
)
```

Supported symbols (from upstream OmniVoice):
- `[laughter]` - Natural laughter
- `[breath]` - Breathing sound
- `[sigh]` - Sighing sound
- `[sniff]` - Sniffing sound
- `[confirmation-en]` - English confirmation sound
- `[question-en]` - English questioning intonation
- `[question-ah]` - Questioning "ah" sound
- `[question-oh]` - Questioning "oh" sound
- `[question-ei]` - Questioning "ei" sound
- `[question-yi]` - Questioning "yi" sound
- `[surprise-ah]` - Surprised "ah" sound
- `[surprise-oh]` - Surprised "oh" sound
- `[surprise-wa]` - Surprised "wa" sound
- `[surprise-yo]` - Surprised "yo" sound
- `[dissatisfaction-hnn]` - Dissatisfied "hnn" sound

### Pronunciation Control

Provide pronunciation hints inline in text (upstream pass-through feature):

**Chinese (Pinyin)**:
```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "input": "这是拼音(pīn yīn)提示的例子"
    }
)
```

**English (CMU Dictionary format)**:
```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "input": "The word read(R IY D) is pronounced differently from read(R EH D)"
    }
)
```

The server passes these hints directly to OmniVoice without modification.

### Advanced Generation Parameters

Fine-tune synthesis quality and characteristics with per-request parameters (upstream OmniVoice pass-through):

```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "input": "Hello world",
        "num_step": 32,                    # Inference steps (1-64, higher=better quality)
        "guidance_scale": 3.0,             # CFG scale (0-10, higher=stronger conditioning)
        "denoise": True,                   # Enable denoising (recommended)
        "t_shift": 0.1,                    # Noise schedule shift (0-2, affects quality/speed)
        "position_temperature": 5.0,       # Voice diversity (0=deterministic, higher=more variation)
        "class_temperature": 0.0,          # Token sampling temperature (0=greedy, higher=random)
        "duration": 3.5,                   # Fixed output duration in seconds (overrides speed)
        "layer_penalty_factor": 0.5,       # Layer penalty factor (>=0.0)
        "preprocess_prompt": True,         # Enable prompt preprocessing
        "postprocess_output": True,        # Enable output postprocessing
        "audio_chunk_duration": 0.5,       # Audio chunk duration in seconds (>0.0)
        "audio_chunk_threshold": 0.1       # Audio chunk threshold in seconds (>0.0)
    }
)
```

**Voice Consistency & Reproducibility:**

For deterministic, reproducible output (same voice every time):
```python
{
    "position_temperature": 0.0,  # Greedy/deterministic voice rendering
    "class_temperature": 0.0      # Greedy token sampling
}
```

This is especially useful for:
- Streaming with consistent voice across sentences
- Reproducible synthesis for testing
- Fixed voice character in production

Higher `position_temperature` (default 5.0) produces more variation from the default design prompt and may cause inconsistency when streaming.

**Fixed Duration for Video Sync:**

Use `duration` to generate audio of exact length for syncing with video or animations:
```python
{
    "duration": 5.0  # Generate exactly 5 seconds of audio
}
```

When both `duration` and `speed` are provided, `duration` takes precedence and `speed` is ignored.

These parameters override server defaults on a per-request basis.
