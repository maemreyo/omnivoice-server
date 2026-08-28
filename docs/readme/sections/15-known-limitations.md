## Known Limitations

### Non-Verbal Tags Need Surrounding Text

A non-verbal tag in a short utterance makes OmniVoice return a steady
low-frequency drone with no speech in it. It is loud and continuous rather than
quiet, so it reads as a corrupt file rather than a failed generation.

Measured: `Hello [laughter] hi.` (3 words) fails 3/3; the same tag in a 13-word
sentence fails 0/3. **Allow roughly 8–10 words of ordinary text per tag.**

It is not specific to any tag, short text alone is fine, and no generation
parameter avoids it — `num_step` 8/16/32 and `position_temperature=0` were each
measured three times on a failing input and all twelve failed.

Affected responses carry `X-No-Speech-Detected: true`.

See [Advanced Features](08-advanced-features.md) and issue #37.

### Streaming Voice Consistency

When using `stream=True` (server-only HTTP streaming transport), each sentence is synthesized independently from the same instructions or default design prompt. With non-zero temperature settings, timbre can still drift across chunks because there is no shared state between sentence-level synthesis calls.

**Workarounds:**

1. **Set position_temperature=0 for deterministic voice rendering (recommended):**
   ```python
   with httpx.stream(
       "POST",
       "http://127.0.0.1:8880/v1/audio/speech",
       json={
           "input": "Long text...",
           "stream": True,
           "position_temperature": 0.0  # Deterministic voice rendering
       }
   ) as response:
       for chunk in response.iter_bytes():
           play_audio(chunk)
   ```
   This minimizes chunk-to-chunk variation and provides more consistent streaming output.

2. **Use one-shot voice cloning for consistent results:**
   ```python
   with open("reference.wav", "rb") as f:
       response = httpx.post(
           "http://127.0.0.1:8880/v1/audio/speech/clone",
           data={"text": "Long text..."},
           files={"ref_audio": f}
       )
   if response.status_code == 200:
       audio_bytes = response.content
   ```

3. **Use explicit instructions for a stable voice character:**
   ```python
   {
       "instructions": "female,british accent",
       "stream": True
   }
   ```

This limitation is inherent to the sentence-by-sentence streaming architecture and does not affect non-streaming synthesis.
