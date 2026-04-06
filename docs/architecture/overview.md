# omnivoice-server — Architecture Document

> **Version**: 2026-04-04
> **Status**: Pre-implementation
> **Audience**: Developers implementing or onboarding to this project

---

## Table of contents

- [omnivoice-server — Architecture Document](#omnivoice-server--architecture-document)
  - [Table of contents](#table-of-contents)
  - [1. Ecosystem positioning](#1-ecosystem-positioning)
    - [Why this repo exists](#why-this-repo-exists)
    - [Relation to similar projects](#relation-to-similar-projects)
  - [2. Layer architecture](#2-layer-architecture)
    - [Layer responsibilities](#layer-responsibilities)
  - [3. Internal component map](#3-internal-component-map)
  - [4. Concurrency model](#4-concurrency-model)
    - [Key invariants](#key-invariants)
    - [What happens under load](#what-happens-under-load)
  - [5. Request lifecycle — non-streaming](#5-request-lifecycle--non-streaming)
  - [6. Request lifecycle — streaming](#6-request-lifecycle--streaming)
    - [Streaming response headers](#streaming-response-headers)
    - [Streaming vs non-streaming trade-offs](#streaming-vs-non-streaming-trade-offs)
  - [7. Voice mode decision tree](#7-voice-mode-decision-tree)
  - [8. Startup \& shutdown sequence](#8-startup--shutdown-sequence)
    - [Startup failure modes](#startup-failure-modes)
  - [9. Profile storage schema](#9-profile-storage-schema)
  - [10. Service dependency graph](#10-service-dependency-graph)
  - [11. Error taxonomy](#11-error-taxonomy)

---

## 1. Ecosystem positioning

This diagram shows **where `omnivoice-server` sits in the broader stack**, from end-user clients down to model weights on disk.

```mermaid
graph TB
    subgraph L0["L0 — Client layer"]
        C1["Python app<br/>(openai SDK)"]
        C2["cURL / HTTP client"]
        C3["Streaming player<br/>(pyaudio)"]
        C4["Future: browser app<br/>web SpeechSynthesis shim"]
    end

    subgraph L1["L1 — omnivoice-server  ◀ THIS REPO"]
        direction LR
        SRV["FastAPI HTTP server<br/>port 8880<br/>OpenAI-compatible API"]
    end

    subgraph L2["L2 — OmniVoice Python SDK"]
        direction LR
        SDK["omnivoice package<br/>k2-fsa/OmniVoice<br/>Apache 2.0"]
        TOK["Higgs Audio Tokenizer<br/>bosonai/higgs-audio-v2-tokenizer<br/>⚠ Boson Community License"]
        WHISP["Whisper ASR<br/>(auto-transcription of ref_audio)"]
    end

    subgraph L3["L3 — Model weights & inference backend"]
        direction LR
        MODEL["OmniVoice weights<br/>k2-fsa/OmniVoice<br/>~3.3 GB on HuggingFace"]
        TORCH["PyTorch 2.8<br/>CUDA / MPS / CPU"]
        HF["HuggingFace Hub<br/>(download & cache)"]
    end

    subgraph L4["L4 — Hardware"]
        GPU["NVIDIA GPU<br/>(CUDA)"]
        MPS["Apple Silicon<br/>(MPS)"]
        CPU["CPU fallback"]
    end

    C1 & C2 & C3 & C4 -->|"HTTP POST /v1/audio/speech<br/>OpenAI-compatible JSON"| SRV
    SRV -->|"model.generate()"| SDK
    SDK --> TOK
    SDK --> WHISP
    SDK -->|"from_pretrained()"| HF
    HF -->|"cache weights"| MODEL
    MODEL --> TORCH
    TORCH --> GPU & MPS & CPU

    style L1 fill:#E1F5EE,stroke:#0F6E56,color:#085041
    style L0 fill:#E6F1FB,stroke:#185FA5,color:#0C447C
    style L2 fill:#FAEEDA,stroke:#BA7517,color:#854F0B
    style L3 fill:#F1EFE8,stroke:#5F5E5A,color:#444441
    style L4 fill:#F1EFE8,stroke:#5F5E5A,color:#444441
```

### Why this repo exists

OmniVoice ships a Python API and a CLI, but **no HTTP server**. That means:
- No drop-in replacement for `api.openai.com/v1/audio/speech`
- No persistent voice profiles across requests
- No concurrent request handling or semaphore-based backpressure
- No observability (`/health`, `/metrics`)

`omnivoice-server` fills this gap as a thin, stateless-ish HTTP adapter layer. It adds **no new ML capabilities** — it only makes the existing ones accessible over HTTP with proper concurrency semantics.

### Relation to similar projects

| Project                     | Model     | OpenAI-compat | Voice cloning         | MPS support |
| --------------------------- | --------- | ------------- | --------------------- | ----------- |
| **omnivoice-server** (this) | OmniVoice | ✅             | ✅ persistent profiles | ✅           |
| kokoro-fastapi              | Kokoro    | ✅             | ❌                     | ❌           |
| CoquiAI/TTS server          | XTTS v2   | ❌             | ✅                     | ❌           |
| local-ai                    | multiple  | ✅             | partial               | partial     |

---

## 2. Layer architecture

Internal layers of `omnivoice-server` itself, from HTTP surface down to hardware.

```mermaid
graph TB
    subgraph HTTP["HTTP surface"]
        R1["/v1/audio/speech"]
        R2["/v1/audio/speech/clone"]
        R3["/v1/voices  +  /v1/voices/profiles"]
        R4["/health  +  /metrics"]
    end

    subgraph MW["Middleware"]
        AUTH["Auth middleware<br/>(Bearer token, optional)"]
    end

    subgraph SVC["Service layer"]
        IS["InferenceService<br/>executor + semaphore"]
        BS["BatchingService<br/>accumulate + dispatch"]
        MS["ModelService<br/>model singleton"]
        PS["ProfileService<br/>disk store"]
        MTS["MetricsService<br/>in-memory counters"]
    end

    subgraph UTIL["Utility layer"]
        AU["audio.py<br/>tensor → WAV / PCM bytes"]
        TU["text.py<br/>sentence splitter"]
    end

    subgraph CFG["Config layer"]
        ST["Settings<br/>(pydantic-settings)<br/>env vars · .env · CLI flags"]
    end

    subgraph INFRA["Infrastructure"]
        TP["ThreadPoolExecutor<br/>max_workers = MAX_CONCURRENT"]
        SEM["asyncio.Semaphore<br/>(MAX_CONCURRENT)"]
        FS["Filesystem<br/>~/.omnivoice/profiles/"]
    end

    R1 & R2 & R3 & R4 --> AUTH
    AUTH --> IS & PS & MTS
    IS --> BS
    BS --> MS
    IS --> UTIL
    IS --> TP & SEM
    PS --> FS
    ST -->|"configures"| IS & MS & PS & AUTH
```

### Layer responsibilities

| Layer                      | Responsibility                                                     | Does NOT do               |
| -------------------------- | ------------------------------------------------------------------ | ------------------------- |
| **HTTP surface** (routers) | Parse/validate request, format response, map errors to HTTP status | Business logic            |
| **Middleware**             | Auth gate, future: rate limiting                                   | Routing                   |
| **Service layer**          | Orchestrate inference, manage state, record metrics                | HTTP concerns             |
| **Utility layer**          | Pure functions (audio encoding, text splitting)                    | Side effects              |
| **Config layer**           | Single source of truth for all tunables                            | Validation beyond type    |
| **Infrastructure**         | Thread pool, semaphore, filesystem                                 | Awareness of domain logic |

---

## 3. Internal component map

Static view of all modules and their relationships.

```mermaid
graph LR
    subgraph pkg["omnivoice_server/"]
        CLI["cli.py<br/>argparse → Settings → uvicorn.run()"]
        APP["app.py<br/>create_app() + lifespan()"]
        CFG["config.py<br/>Settings(BaseSettings)"]

        subgraph routers["routers/"]
            RSPEECH["speech.py<br/>POST /v1/audio/speech<br/>POST /v1/audio/speech/clone"]
            RVOICES["voices.py<br/>GET /v1/voices<br/>CRUD /v1/voices/profiles"]
            RHEALTH["health.py<br/>GET /health<br/>GET /metrics"]
        end

        subgraph services["services/"]
            SMODEL["model.py<br/>ModelService"]
            SINFER["inference.py<br/>InferenceService<br/>SynthesisRequest / Result"]
            SBATCH["batching.py<br/>BatchingService<br/>accumulate + batch dispatch"]
            SPROFILE["profiles.py<br/>ProfileService"]
            SMETRIC["metrics.py<br/>MetricsService"]
        end

        subgraph utils["utils/"]
            UAUDIO["audio.py<br/>tensor_to_wav_bytes()<br/>tensor_to_pcm16_bytes()"]
            UTEXT["text.py<br/>split_sentences()"]
        end
    end

    CLI --> CFG
    CLI --> APP
    APP --> CFG
    APP --> SMODEL & SINFER & SPROFILE & SMETRIC
    APP --> RSPEECH & RVOICES & RHEALTH

    RSPEECH --> SINFER & SPROFILE & SMETRIC & UAUDIO & UTEXT
    RVOICES --> SPROFILE
    RHEALTH --> SMETRIC

    SINFER --> SMODEL & UAUDIO
    SINFER --> SBATCH
    SBATCH --> SMODEL
    SMODEL -->|"OmniVoice.from_pretrained()"| EXT_OV["omnivoice<br/>(external package)"]
```

---

## 4. Concurrency model

This is the most important architectural decision. Understand this before touching `InferenceService`.

### With dynamic batching (default)

```mermaid
sequenceDiagram
    participant C1 as Client 1
    participant C2 as Client 2
    participant EL as asyncio event loop
    participant BS as BatchingService<br/>(background loop)
    participant SEM as batch_semaphore(N)
    participant EX as ThreadPoolExecutor
    participant GPU as GPU (blocking)

    C1->>EL: POST /v1/audio/speech
    EL->>BS: submit(req1) → Future
    C2->>EL: POST /v1/audio/speech
    EL->>BS: submit(req2) → Future
    Note over BS: Accumulate until batch_max_size<br/>or batch_timeout_ms elapsed
    BS->>SEM: await batch_semaphore.acquire()
    SEM-->>BS: acquired
    BS->>EX: run_in_executor(_run_batch_sync)
    EX->>GPU: model.generate(text=[text1, text2]) [BLOCKING]
    GPU-->>EX: [tensor1, tensor2]
    EX-->>BS: [SynthesisResult1, SynthesisResult2]
    BS->>SEM: semaphore.release()
    BS-->>EL: resolve Future1, Future2
    EL-->>C1: Response(audio1)
    EL-->>C2: Response(audio2)
```

Requests are grouped by compatible generation parameters (num_step, guidance_scale, etc.) into parameter groups. Each group is dispatched as a single batched `model.generate()` call. The `batch_semaphore` limits concurrent batch dispatches to `max_concurrent` threads.

### Without batching (--no-batch)

```mermaid
sequenceDiagram
    participant C as Client
    participant EL as asyncio event loop<br/>(main thread)
    participant SEM as Semaphore(N)
    participant EX as ThreadPoolExecutor<br/>(N worker threads)
    participant GPU as GPU/MPS<br/>(blocking)

    C->>EL: POST /v1/audio/speech
    Note over EL: Validate input (fast, sync OK on event loop)
    EL->>SEM: await semaphore.acquire()
    Note over SEM: If N slots full → suspend coroutine,<br/>event loop serves other requests
    SEM-->>EL: acquired
    EL->>EX: await loop.run_in_executor(executor, _run_sync)
    Note over EX: Thread unblocks event loop.<br/>Event loop is free to handle other requests.
    EX->>GPU: model.generate() [BLOCKING]
    GPU-->>EX: tensors
    Note over EX: gc.collect() + empty_cache() (memory cleanup)
    EX-->>EL: SynthesisResult
    EL->>SEM: semaphore.release()
    EL-->>C: Response(audio_bytes)
```

### Key invariants

| Rule                                   | Why                                                                                                  |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `workers=1` in uvicorn                 | One model in VRAM. Multi-process = N copies of weights.                                              |
| `ThreadPoolExecutor(max_workers=N)`    | N = `MAX_CONCURRENT`. Controls concurrent batch dispatches (batching) or individual requests (legacy).|
| `batch_semaphore(N)` (batching mode)   | Prevents > N concurrent batch dispatches to the executor. Provides backpressure.                     |
| `asyncio.Semaphore(N)` (legacy mode)   | Prevents > N concurrent inferences. Queue forms in the event loop.                                   |
| `await asyncio.wait_for(..., timeout)` | Wraps executor call. Raises `TimeoutError` after `request_timeout_s`.                                |
| `_cleanup_memory()` in `finally`       | Runs on every inference — success or exception. Mitigates Torch 2.8 memory leak (upstream issue #9). |

### What happens under load

**With batching (default):**
```
1 request  → waits up to batch_timeout_ms, then dispatches alone
2 requests → both accumulated, dispatched as batch of 2
8 requests → dispatched as batch of 8 (batch_max_size default)
9 requests → batch of 8 dispatched, 9th starts next batch
             different param groups dispatch independently
```

**Without batching (--no-batch):**
```
1 request  → runs immediately
2 requests → both run simultaneously (N=2 default)
3 requests → req #3 suspends on semaphore, event loop stays live
             req #3 resumes when req #1 or #2 completes
N+k requests → k requests queue in asyncio, none are rejected
              (until request_timeout_s exceeded → 504)
```

---

## 5. Request lifecycle — non-streaming

```mermaid
flowchart TD
    A([Client: POST /v1/audio/speech]) --> B{Auth check}
    B -->|invalid key| ERR401([401 Unauthorized])
    B -->|ok / no auth| C[Pydantic validation<br/>SpeechRequest]
    C -->|validation error| ERR422([422 Unprocessable Entity])
    C -->|valid| D[_parse_voice]

    D -->|"voice='auto'"| MODE_AUTO[mode='auto']
    D -->|"voice='design:...'"| MODE_DESIGN[mode='design'\ninstruct=attributes]
    D -->|"voice='clone:id'"| LOOKUP{ProfileService\nlookup profile}
    LOOKUP -->|not found| ERR404([404 Not Found])
    LOOKUP -->|found| MODE_CLONE[mode='clone'\nref_audio_path=...\nref_text=...]

    MODE_AUTO & MODE_DESIGN & MODE_CLONE --> E[Build SynthesisRequest]
    E --> F{stream=True?}
    F -->|yes| STREAM([→ See streaming diagram])

    F -->|no| G[InferenceService.synthesize]
    G --> H{semaphore acquired?}
    H -->|wait| H
    H -->|acquired| I[ThreadPoolExecutor\n_run_sync]
    I --> J[model.generate]
    J -->|TimeoutError| ERR504([504 Gateway Timeout])
    J -->|Exception| ERR500([500 Internal Server Error])
    J -->|tensors| K[tensor→WAV or PCM bytes]
    K --> L[metrics_svc.record_success]
    L --> M([200 OK\naudio/wav or audio/pcm])
```

---

## 6. Request lifecycle — streaming

Streaming splits the input into sentences and synthesizes each independently, yielding PCM chunks as they complete.

```mermaid
flowchart TD
    A([stream=True branch]) --> B["split_sentences(text, max_chars=400)"]
    B --> C{sentences empty?}
    C -->|yes| DONE([yield nothing, close])
    C -->|no| D[for sentence in sentences]

    D --> E[Build per-sentence SynthesisRequest]
    E --> F[InferenceService.synthesize]
    F -->|TimeoutError| WARN1[log warning\nstop generator]
    F -->|Exception| WARN2[log warning\nstop generator]
    F -->|SynthesisResult| G[tensor_to_pcm16_bytes]
    G --> H([yield PCM bytes to client])
    H --> D

    WARN1 & WARN2 --> TRUNC([client receives truncated but valid PCM stream\nno HTTP error possible after streaming started])
```

### Streaming response headers

```
Content-Type: audio/pcm
X-Audio-Sample-Rate: 24000
X-Audio-Channels: 1
X-Audio-Bit-Depth: 16
X-Audio-Format: pcm-int16-le
Transfer-Encoding: chunked
```

Client must know these params **before** the first byte arrives — they are in the HTTP response headers, not embedded in the audio stream (no WAV header).

### Streaming vs non-streaming trade-offs

|                  | Non-streaming                | Streaming                               |
| ---------------- | ---------------------------- | --------------------------------------- |
| First audio byte | After full synthesis         | After first sentence                    |
| Latency (TTFA)   | High (~RTF × total_duration) | Low (~RTF × first_sentence)             |
| Error recovery   | HTTP 500/504                 | Truncated stream (silent)               |
| Metrics recorded | ✅ per request                | ✅ per sentence chunk *(see fix §below)* |
| Use case         | Batch, short texts           | Real-time, long texts                   |

---

## 7. Voice mode decision tree

```mermaid
flowchart TD
    A([voice= field in request]) --> B{value?}

    B -->|"'auto' or empty"| AUTO["mode = 'auto'\nmodel picks random voice"]
    B -->|"starts with 'design:'"| DES_PARSE["extract attributes string\ne.g. 'female, british accent'"]
    B -->|"starts with 'clone:'"| CLONE_PARSE["extract profile_id"]
    B -->|"anything else"| FALLBACK["treated as design attributes\n(convenience shorthand)"]

    DES_PARSE --> DES_CHK{attributes empty?}
    DES_CHK -->|yes| E422([422 'design: requires attributes'])
    DES_CHK -->|no| DESIGN["mode = 'design'\ninstruct = attributes"]

    CLONE_PARSE --> CLONE_CHK{profile_id empty?}
    CLONE_CHK -->|yes| E422B([422 'clone: requires profile_id'])
    CLONE_CHK -->|no| LOOKUP["ProfileService.get_ref_audio_path(profile_id)"]
    LOOKUP --> FOUND_CHK{profile exists?}
    FOUND_CHK -->|no| E404([404 Profile not found])
    FOUND_CHK -->|yes| CLONE["mode = 'clone'\nref_audio_path = /profiles/id/ref_audio.wav\nref_text = from meta.json (or None → Whisper)"]

    FALLBACK --> DESIGN
    AUTO & DESIGN & CLONE --> SYNTH([→ SynthesisRequest])
```

---

## 8. Startup & shutdown sequence

```mermaid
sequenceDiagram
    participant CLI as cli.py
    participant APP as app.py lifespan()
    participant MS as ModelService
    participant EX as ThreadPoolExecutor
    participant FS as Filesystem
    participant UV as uvicorn

    CLI->>APP: create_app(cfg)
    CLI->>UV: uvicorn.run(app, workers=1)
    UV->>APP: lifespan(app) — startup phase

    APP->>FS: profile_dir.mkdir(parents=True)
    APP->>MS: ModelService(cfg)
    APP->>MS: await model_svc.load()
    Note over MS: Runs in temporary 1-thread executor<br/>Blocks startup (intentional)<br/>Tries float16 → bfloat16 → float32<br/>Runs 4-step sanity generate to detect NaN
    MS-->>APP: model loaded (or RuntimeError → crash)

    APP->>EX: ThreadPoolExecutor(max_workers=N)
    APP->>APP: InferenceService(model_svc, executor, cfg)
    APP->>APP: BatchingService(model_svc, executor, cfg)
    APP->>APP: await batching_svc.start()
    Note over APP: Starts background dispatch loop
    APP->>APP: ProfileService(profile_dir)
    APP->>APP: MetricsService()
    APP->>APP: record start_time

    APP-->>UV: yield  ← server starts accepting requests

    Note over UV: ... server live ...

    UV->>APP: shutdown signal (SIGINT / SIGTERM)
    APP->>APP: await batching_svc.stop()
    Note over APP: Cancels dispatch loop,<br/>fails pending requests
    APP->>EX: executor.shutdown(wait=False)
    Note over EX: In-flight inferences may be interrupted.<br/>wait=False avoids hanging on long synthesis.
    APP-->>UV: done
```

### Startup failure modes

| Failure                             | Outcome                                                  |
| ----------------------------------- | -------------------------------------------------------- |
| All dtype candidates fail on device | `RuntimeError` — process exits, no port bound            |
| Profile dir not writable            | `PermissionError` on first profile write, not at startup |
| HuggingFace unreachable (no cache)  | `OSError` from `from_pretrained()` — process exits       |
| Port already in use                 | uvicorn error before lifespan runs                       |

---

## 9. Profile storage schema

Voice cloning profiles are stored on disk under `~/.omnivoice/profiles/` (configurable).

```
~/.omnivoice/
└── profiles/
    ├── alice-voice/
    │   ├── ref_audio.wav          ← reference audio (any duration, recommend 5–30s)
    │   └── meta.json              ← profile metadata
    ├── narrator-deep/
    │   ├── ref_audio.wav
    │   └── meta.json
    └── ...
```

**`meta.json` schema:**

```json
{
  "name": "alice-voice",
  "ref_text": "Hello, this is a sample of my voice for cloning.",
  "created_at": "2026-04-04T12:00:00+00:00"
}
```

| Field        | Type           | Description                                                                  |
| ------------ | -------------- | ---------------------------------------------------------------------------- |
| `name`       | string         | Same as `profile_id` (directory name)                                        |
| `ref_text`   | string \| null | Transcript of `ref_audio.wav`. `null` → Whisper auto-transcribes on each use |
| `created_at` | ISO 8601 UTC   | Creation timestamp                                                           |

**Profile ID constraints:** `^[a-zA-Z0-9_-]{1,64}$` — alphanumeric, dashes, underscores only. Enforced at both API (Pydantic) and storage (sanitize function) layers.

```mermaid
erDiagram
    PROFILE {
        string profile_id PK "directory name, 1-64 chars"
        string name "= profile_id"
        string ref_text "nullable, Whisper fallback"
        datetime created_at "UTC ISO 8601"
    }
    REF_AUDIO {
        bytes content "WAV file bytes"
        string path "profiles/id/ref_audio.wav"
    }
    PROFILE ||--|| REF_AUDIO : "has one"
```

---

## 10. Service dependency graph

Which services depend on which, and what shared state they own.

```mermaid
graph TD
    CFG[Settings<br/>pydantic-settings]

    MS["ModelService<br/>owns: OmniVoice instance<br/>state: _model, _loaded"]
    IS["InferenceService<br/>owns: Semaphore, executor ref<br/>state: stateless between requests"]
    PS["ProfileService<br/>owns: profile_dir path<br/>state: filesystem (external)"]
    MTS["MetricsService<br/>owns: counters, latency deque<br/>state: in-memory, resets on restart"]

    BS["BatchingService<br/>owns: pending queue, dispatch loop, batch_semaphore<br/>state: in-memory, resets on restart"]

    EX["ThreadPoolExecutor<br/>(created in lifespan, shared)"]
    FS["~/.omnivoice/profiles/"]

    CFG -->|"model_id, device, num_step"| MS
    CFG -->|"max_concurrent, request_timeout_s, num_step"| IS
    CFG -->|"batch_max_size, batch_timeout_ms"| BS
    CFG -->|"profile_dir"| PS
    CFG -->|"max_concurrent"| EX

    MS -->|"model singleton"| IS
    EX -->|"thread pool"| IS
    BS -->|"batched generate()"| MS
    EX -->|"thread pool"| BS
    FS -->|"read/write"| PS

    IS -.->|"used by"| RSPEECH["routers/speech.py"]
    PS -.->|"used by"| RSPEECH
    PS -.->|"used by"| RVOICES["routers/voices.py"]
    MTS -.->|"used by"| RSPEECH
    MTS -.->|"used by"| RHEALTH["routers/health.py"]
    MS -.->|"used by"| RHEALTH
```

---

## 11. Error taxonomy

```mermaid
flowchart LR
    subgraph CLIENT["Client errors (4xx)"]
        E401["401 Unauthorized\nWrong or missing Bearer token"]
        E404["404 Not Found\nProfile ID does not exist"]
        E409["409 Conflict\nProfile already exists (no overwrite)"]
        E422["422 Unprocessable Entity\nPydantic validation failure\nempty text, bad profile_id,\nbad voice: prefix"]
    end

    subgraph SERVER["Server errors (5xx)"]
        E500["500 Internal Server Error\nmodel.generate() threw unexpected exception"]
        E504["504 Gateway Timeout\nasyncio.TimeoutError after request_timeout_s"]
    end

    subgraph OK["Success (2xx)"]
        E200["200 OK\naudio/wav or audio/pcm bytes"]
        E201["201 Created\nprofile metadata JSON"]
        E204["204 No Content\nprofile deleted"]
    end
```

---

*Document generated from [../system/specification.md](../system/specification.md) v2026-04-04. See [../design/dataflow.md](../design/dataflow.md) for per-endpoint data flow details.*
