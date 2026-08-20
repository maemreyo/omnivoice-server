## Known Limitations

### Streaming Voice Consistency

The server preserves OmniVoice's native long-form conditioning for auto/design
requests: the complete input is sent to one model generation call and the
result is delivered through the HTTP streaming response. This keeps chunk-0
voice conditioning and whole-output postprocessing intact, but the first audio
bytes are not available until that model call completes.

Long clone requests retain sentence-level HTTP chunks. Their reference prompt
is prepared once and reused for every chunk, so stored profiles and one-shot
references do not re-encode the reference for each sentence. The chunks are
still separate OmniVoice generations and can vary slightly with non-zero
temperature settings.

**Workarounds:**

1. **Set position_temperature=0 for deterministic clone chunk rendering (recommended):**
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
   This minimizes variation between clone chunks.

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

The server's design/auto streaming path is intentionally buffered until the
complete OmniVoice generation returns. This limitation affects time-to-first
byte, not the generated voice continuity. Non-streaming synthesis uses the
same complete-request model path.
