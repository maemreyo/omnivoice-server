## Known Limitations

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
