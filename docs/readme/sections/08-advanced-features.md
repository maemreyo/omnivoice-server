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

**Tags outside this list are not errors — they are synthesized as literal text.**
`[laugh]` is not `[laughter]`; it becomes the spoken word "laugh". The server logs
a warning and returns the offending tags in an `X-Unknown-Nonverbal-Tags`
response header so typos are visible without listening to the output.

#### Reliability: give tags enough text around them

A non-verbal tag in a short utterance makes OmniVoice emit a steady
low-frequency drone containing no speech at all — at normal volume, so it is
easy to mistake for a corrupt file rather than a failed generation (issue #37).

What governs it is the amount of ordinary text per tag, not the tag itself.
Measured against `k2-fsa/OmniVoice`, three runs each, using zero-crossing rate
per 250ms window to detect the presence of speech:

| Text with one `[laughter]` tag | Words | Failed |
|--------------------------------|-------|--------|
| `Hello [laughter] hi.` | 3 | **3/3** |
| `Hello [laughter] this is amazing.` | 5 | **2/3** |
| `Hello there [laughter] this is really amazing.` | 7 | 0/3 |
| `Hello there my friend [laughter] this is really quite amazing.` | 10 | 0/3 |
| `Hello there my dear old friend [laughter] this is really quite amazing today.` | 13 | 0/3 |

**Rule of thumb: allow roughly 8–10 words of ordinary text per tag.** The
reported failure — three tags across eight words — works out at under three
words per tag and fails every time.

Things that are *not* the cause, each measured:

- **Not tag-specific.** `[laughter]`, `[sigh]`, `[breath]`, `[sniff]` and
  `[question-en]` all behave identically: fine in a long sentence, drone in a
  short one.
- **Not short text by itself.** The same short sentences without any tag
  synthesize normally.
- **Not a parameter you can tune around.** `num_step` at 8, 16 and 32, and
  `position_temperature=0`, were each tried three times on the failing input;
  all twelve results failed.

```python
# Reliable — the tag has room to breathe
{"input": "Hello there my friend [laughter] this is really quite amazing."}

# Fails — three tags across eight words
{"input": "Hello [laughter] this is amazing [breath] really cool [sigh]"}
```

The server checks its own output and sets `X-No-Speech-Detected: true` when a
generation comes back as a drone, so this is visible without listening to every
file. It does not retry: no parameter recovers it, so a retry would only double
the latency. Disable the check with `--no-detect-no-speech`.

### Named Voices from a Directory

OpenAI-compatible clients send a bare `voice` string and have no field for
`instructions`, so a voice design cannot be expressed through them. Dropping a
`.txt` file into the voice directory gives a design a name, and the name is all
such a client needs to send.

```bash
mkdir -p ~/.local/share/omnivoice/voices
cat > ~/.local/share/omnivoice/voices/canadian-lady.txt <<'EOF'
# Anything after # is a comment.
description: For my podcast app
female, young adult, canadian accent
seed: 4242
EOF
```

The voice is now selectable by filename, from any client:

```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={"input": "Hello", "voice": "canadian-lady"}
)
```

It also appears in `GET /v1/voices` with `"type": "file"`.

**Format.** Any line reading `key: value` (or `key = value`) whose key is a
known parameter sets that parameter. Every other non-comment line contributes to
the voice design. Supported keys:

| Key | Purpose |
|-----|---------|
| `seed` | Fix the RNG so this voice sounds the same every time |
| `speed` | Playback speed |
| `num_step` | Inference steps |
| `guidance_scale`, `t_shift`, `position_temperature`, `class_temperature` | Generation tuning |
| `denoise` | `true` / `false` |
| `duration` | Fixed output length |
| `language` | Language code |
| `description` | Shown in `/v1/voices`; not sent to the model |
| `instructions` | Voice design, if you prefer stating it explicitly |

**Precedence.** Parameters in a file are defaults. Anything the request sets
explicitly wins. Voice files also take precedence over the built-in OpenAI
preset names, so a `nova.txt` replaces the built-in `nova` — the server logs a
warning at startup when that happens.

**Validation.** Attributes are checked the same way `instructions` is. A file
that fails validation is skipped with a warning at startup rather than
producing strange audio later, and the voice simply does not appear.

Files are re-read when they change, so voices can be added or edited without
restarting the server. Set the directory with `--voice-dir`.

### Reproducible Output

Synthesis is random by default: the same request twice gives two different
voices. Pass a `seed` to make it repeatable — the same seed with the same text
and parameters produces the same audio.

```python
response = httpx.post(
    "http://127.0.0.1:8880/v1/audio/speech",
    json={
        "input": "This will sound the same every time.",
        "instructions": "female, young adult, canadian accent",
        "seed": 1234
    }
)
```

Set a server-wide default with `--seed 1234`; individual requests can still
override it.

**Concurrency caveat**: the underlying RNG is process-global. Seeded requests are
serialized against each other, but an unseeded request generating at the same
moment still advances that RNG. For bit-exact reproducibility, run with
`--max-concurrent 1`.

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
