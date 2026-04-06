# omnivoice-server — Data Flow Reference

> Detailed data transformation path for each endpoint, from HTTP bytes to audio bytes and back.

---

## Endpoint index

| Endpoint                                          | Method               | Auth required | Returns         |
| ------------------------------------------------- | -------------------- | ------------- | --------------- |
| [`/v1/audio/speech`](#v1audiospeech)              | POST                 | Optional      | WAV / PCM bytes |
| [`/v1/audio/speech/clone`](#v1audiospeechclone)   | POST                 | Optional      | WAV bytes       |
| [`/v1/audio/cache`](#v1audiocache)                | DELETE               | Optional      | JSON            |
| [`/v1/voices`](#v1voices)                         | GET                  | Optional      | JSON            |
| [`/v1/voices/profiles`](#v1voicesprofiles)        | POST                 | Optional      | JSON (201)      |
| [`/v1/voices/profiles/{id}`](#v1voicesprofilesid) | GET / PATCH / DELETE | Optional      | JSON / 204      |
| [`/health`](#health)                              | GET                  | ❌ Never       | JSON            |
| [`/metrics`](#metrics)                            | GET                  | ❌ Never       | JSON            |

---

## /v1/audio/speech

### Non-streaming data flow

```
HTTP Request
  │
  ├─ JSON body ──────────────────────────────────────────────────────────────────────
  │   {                                               Pydantic: SpeechRequest
  │     "model": "omnivoice",    ← any value OK
  │     "input": "<text>",       ← 1–10,000 chars
  │     "voice": "auto|design:...|clone:...",
  │     "response_format": "wav|pcm",
  │     "speed": 1.0,            ← 0.25–4.0
  │     "stream": false,
  │     "num_step": null         ← 1–64 or null
  │   }
  │
  ├─ voice string parsing (_parse_voice) ────────────────────────────────────────────
  │   "auto"              → mode="auto", instruct=None, ref_path=None
  │   "design:female,..."→ mode="design", instruct="female,..."
  │   "clone:myprofile"  → mode="clone", ref_path="/profiles/myprofile/ref_audio.wav"
  │                                       ref_text=meta.json["ref_text"] or None
  │
  ├─ SynthesisRequest built ─────────────────────────────────────────────────────────
  │   text, mode, instruct, ref_audio_path, ref_text, speed, num_step
  │
  ├─ Cache lookup (non-streaming only) ──────────────────────────────────────────────
  │   key = SHA-256(voice, text, speed, num_step, guidance_scale, ...)
  │   AudioCache.get(key)
  │   → HIT:  return cached audio bytes immediately (X-Cache: HIT)
  │   → MISS: proceed to inference
  │
  ├─ InferenceService.synthesize() [async] ──────────────────────────────────────────
  │   └─ asyncio.wait_for(                       timeout = request_timeout_s (120s)
  │        run_in_executor(executor, _run_sync)  releases event loop while GPU runs
  │      )
  │      └─ _run_sync():
  │           model.generate(**kwargs)           OmniVoice blocking call
  │           → list[torch.Tensor]               each (1, T) float32 at 24kHz
  │           gc.collect() + empty_cache()       memory cleanup
  │           → SynthesisResult(tensors, duration_s, latency_s)
  │
  ├─ Audio encoding ─────────────────────────────────────────────────────────────────
  │   response_format="wav" → tensors_to_wav_bytes()
  │                           torch.cat(tensors, dim=-1)
  │                           torchaudio.save(buf, tensor, 24000, format="wav",
  │                                           encoding="PCM_S", bits_per_sample=16)
  │                           → bytes (RIFF WAV, PCM 16-bit signed)
  │
  │   response_format="pcm" → tensor_to_pcm16_bytes() per tensor, concatenated
  │                           (flat * 32767).clamp(-32768,32767).to(int16).tobytes()
  │                           → bytes (raw PCM, no header, int16 little-endian)
  │
  └─ HTTP Response ──────────────────────────────────────────────────────────────────
      Status: 200
      Content-Type: audio/wav | audio/pcm
      X-Audio-Duration-S: <seconds>
      X-Synthesis-Latency-S: <seconds>
      X-Cache: HIT | MISS
      Body: <audio bytes>
      → AudioCache.put(key, audio_bytes) on MISS
```

### Streaming data flow

```
HTTP Request (stream=true)
  │
  ├─ [same parsing as above → SynthesisRequest]
  │
  ├─ split_sentences(text, max_chars=400) ───────────────────────────────────────────
  │   regex splits on sentence boundaries (. ! ? newline + uppercase/CJK)
  │   protects: decimals (3.14), URLs, abbreviations
  │   → ["Sentence one.", "Sentence two.", ...]
  │
  ├─ StreamingResponse generator starts ─────────────────────────────────────────────
  │   HTTP 200 sent immediately with headers:
  │   Content-Type: audio/pcm
  │   X-Audio-Sample-Rate: 24000
  │   X-Audio-Channels: 1
  │   X-Audio-Bit-Depth: 16
  │   Transfer-Encoding: chunked
  │
  ├─ for sentence in sentences: ─────────────────────────────────────────────────────
  │   │
  │   ├─ InferenceService.synthesize(per-sentence SynthesisRequest)
  │   │   [same thread pool path as non-streaming]
  │   │
  │   ├─ tensor_to_pcm16_bytes(tensor) → raw PCM chunk
  │   │
  │   └─ yield bytes → HTTP chunked transfer to client
  │      client can begin playing the first sentence's audio
  │      while subsequent sentences are being synthesized
  │
  └─ generator exhausted → connection closed
     (errors mid-stream → generator returns, client sees truncated PCM)
```

---

## /v1/audio/speech/clone

One-shot cloning without a saved profile. Ref audio is temp-file-backed.

```
HTTP Request (multipart/form-data)
  │
  ├─ Form fields:
  │   text        (str, 1–10,000 chars)
  │   ref_audio   (UploadFile)              must be non-empty
  │   ref_text    (str | None)              None → Whisper auto-transcribes
  │   speed       (float, 0.25–4.0)
  │   num_step    (int | None)
  │
  ├─ Upload handling ─────────────────────────────────────────────────────────────────
  │   await ref_audio.read() → bytes
  │   validate size (P2 patch: max_ref_audio_mb)
  │   write to tempfile(suffix=".wav")      OmniVoice requires a path, not bytes
  │   tmp_path = tmp.name
  │
  ├─ [same inference path as /v1/audio/speech with mode="clone"]
  │
  ├─ finally: Path(tmp_path).unlink(missing_ok=True)   always delete temp file
  │
  └─ HTTP Response: 200, audio/wav
```

---

## /v1/voices

Read-only. No inference involved.

```
HTTP GET /v1/voices
  │
  ├─ Built-in voices (hardcoded):
  │   { id: "auto", type: "auto" }
  │   { id: "design:<attributes>", type: "design", attributes_reference: {...} }
  │
  ├─ ProfileService.list_profiles() ─────────────────────────────────────────────────
  │   iterate profile_dir/
  │   for each subdir: read meta.json
  │   → [{ profile_id, name, ref_text, created_at }, ...]
  │
  └─ Response: { voices: [...built_in, ...clone_voices], design_attributes: {...}, total: N }
```

---

## /v1/voices/profiles

### POST — create profile

```
HTTP POST /v1/voices/profiles (multipart/form-data)
  │
  ├─ Form: profile_id (^[a-zA-Z0-9_-]{1,64}$), ref_audio, ref_text?, overwrite?
  │
  ├─ Validate audio bytes (size + format — P2, P5 patches)
  │
  ├─ ProfileService.save_profile()
  │   sanitize profile_id (strip non-alnum chars)
  │   profile_dir/<profile_id>/
  │     ref_audio.wav  ← write bytes
  │     meta.json      ← write { name, ref_text, created_at }
  │
  └─ Response: 201, { profile_id, name, ref_text, created_at }
              409 if exists and overwrite=False
```

### DELETE — remove profile

```
HTTP DELETE /v1/voices/profiles/{profile_id}
  │
  ├─ ProfileService.delete_profile(profile_id)
  │   check profile_dir/<profile_id>/ exists
  │   shutil.rmtree(profile_path)
  │
  └─ Response: 204 No Content
              404 if not found
```

### PATCH — update profile (P7 patch)

```
HTTP PATCH /v1/voices/profiles/{profile_id}
  │
  ├─ Verify profile exists (→ 404 if not)
  ├─ If ref_audio provided: validate + overwrite ref_audio.wav + rewrite meta.json
  ├─ If only ref_text: read existing audio, rewrite meta.json with new ref_text
  │
  └─ Response: 200, updated metadata JSON
```

---

## /v1/audio/cache

```
DELETE /v1/audio/cache → 200 (auth required if configured)
{
  "cleared": {
    "cache_entries": 42,
    "cache_bytes": 12345678,
    "cache_mb": 11.77,
    "cache_max_mb": 512,
    "cache_hits": 100,
    "cache_misses": 42,
    "cache_evictions": 3,
    "cache_hit_rate": 0.704
  }
}
```

Returns stats at the moment of clearing, then wipes all cached entries.
Returns 404 if cache is disabled.

---

## /health

```
GET /health → always 200 (auth bypassed)
{
  "status": "ok" | "loading",   ← "loading" if model not yet ready
  "model": "k2-fsa/OmniVoice",
  "device": "mps" | "cuda" | "cpu",
  "num_step": 16,
  "max_concurrent": 2,
  "cache_enabled": true,
  "cache_max_mb": 512,
  "uptime_s": 42.1
}
```

---

## /metrics

```
GET /metrics → always 200 (auth bypassed)
{
  "requests_total": 142,
  "requests_success": 138,
  "requests_error": 3,
  "requests_timeout": 1,
  "mean_latency_ms": 1240.5,
  "p95_latency_ms": 2100.0,
  "ram_mb": 5432.1,
  "cache_entries": 42,
  "cache_mb": 11.77,
  "cache_max_mb": 512,
  "cache_hits": 100,
  "cache_misses": 42,
  "cache_evictions": 3,
  "cache_hit_rate": 0.704
}
```

Cache fields are included when `cache_enabled=true` (default).

Note: After applying **P1 patch**, streaming requests are included in these counters. Prior to the patch, streaming requests were not counted.

---

## Audio format reference

| Property               | Value                           | Notes                                         |
| ---------------------- | ------------------------------- | --------------------------------------------- |
| Sample rate            | 24,000 Hz                       | Fixed — OmniVoice outputs 24kHz               |
| Channels               | 1 (mono)                        | Always mono                                   |
| Bit depth              | 16-bit signed int               | For WAV and PCM outputs                       |
| Byte order             | Little-endian                   | Standard for PCM on x86 and ARM               |
| WAV encoding           | PCM_S                           | torchaudio `encoding="PCM_S"`                 |
| PCM format             | Raw bytes, no header            | Client must know params from response headers |
| Float range (internal) | [-1.0, 1.0]                     | Tensor dtype float32 inside the model         |
| Conversion             | `× 32767`, clamp, cast to int16 | ~0.003% clipping risk on clipped speech       |

### Reconstructing a PCM stream on the client

```python
import pyaudio
import requests

p = pyaudio.PyAudio()
r = requests.post(
    "http://localhost:8880/v1/audio/speech",
    json={"input": "Hello world", "stream": True},
    stream=True,
)

sample_rate = int(r.headers["X-Audio-Sample-Rate"])   # 24000
stream = p.open(format=pyaudio.paInt16, channels=1, rate=sample_rate, output=True)

for chunk in r.iter_content(chunk_size=4096):
    stream.write(chunk)

stream.stop_stream()
stream.close()
p.terminate()
```
