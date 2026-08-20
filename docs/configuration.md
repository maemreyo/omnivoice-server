# Configuration Reference

All settings can be configured via environment variables with the `OMNIVOICE_` prefix, a `.env` file in the working directory, or CLI flags.

Priority: **CLI flags > environment variables > .env file > defaults**

## Server

| Variable | CLI Flag | Type | Default | Description |
|----------|----------|------|---------|-------------|
| `OMNIVOICE_HOST` | `--host` | string | `127.0.0.1` | Bind address. Use `0.0.0.0` to accept external connections. |
| `OMNIVOICE_PORT` | `--port` | int (0–65535) | `8880` | Port to listen on. `0` = OS assigns an ephemeral port. |
| `OMNIVOICE_LOG_LEVEL` | `--log-level` | string | `info` | Verbosity: `debug`, `info`, `warning`, `error`. |
| `OMNIVOICE_API_KEY` | `--api-key` | string | *(none)* | Bearer token for auth. Empty = no auth required. |

## Model

| Variable | CLI Flag | Type | Default | Description |
|----------|----------|------|---------|-------------|
| `OMNIVOICE_MODEL_ID` | `--model` | string | `k2-fsa/OmniVoice` | HuggingFace repo ID or local path. |
| `OMNIVOICE_MODEL_CACHE_DIR` | *(env only)* | path | *(HF default)* | Override HuggingFace model cache directory. |
| `OMNIVOICE_DEVICE` | `--device` | string | `cpu` | Compute device: `cpu`, `cuda`, `mps`, `auto`. |
| `OMNIVOICE_NUM_STEP` | `--num-step` | int (1–64) | `32` | Diffusion steps. Higher = better quality, slower. |

## Generation Defaults

These are server-level defaults. Per-request overrides are supported via API fields.

| Variable | CLI Flag | Type | Default | Description |
|----------|----------|------|---------|-------------|
| `OMNIVOICE_GUIDANCE_SCALE` | `--guidance-scale` | float (0–10) | `2.0` | CFG scale. Higher = stronger voice conditioning. |
| `OMNIVOICE_DENOISE` | `--denoise` / `--no-denoise` | bool | `true` | Enable upstream denoising. Recommended on. |
| `OMNIVOICE_T_SHIFT` | `--t-shift` | float (0–2) | `0.1` | Noise schedule shift. |
| `OMNIVOICE_POSITION_TEMPERATURE` | `--position-temperature` | float (0–10) | `5.0` | Voice diversity. `0` = deterministic/reproducible. |
| `OMNIVOICE_CLASS_TEMPERATURE` | `--class-temperature` | float (0–2) | `0.0` | Token sampling temperature. `0` = greedy. |

## Inference

| Variable | CLI Flag | Type | Default | Description |
|----------|----------|------|---------|-------------|
| `OMNIVOICE_MAX_CONCURRENT` | `--max-concurrent` | int (1–16) | `2` | Max simultaneous inference requests. |
| `OMNIVOICE_REQUEST_TIMEOUT_S` | `--timeout` | int | `120` | Seconds before a request times out (returns 504). |
| `OMNIVOICE_SHUTDOWN_TIMEOUT` | `--shutdown-timeout` | int (1–300) | `10` | Seconds to wait for in-flight requests on shutdown. |

## Storage

| Variable | CLI Flag | Type | Default | Description |
|----------|----------|------|---------|-------------|
| `OMNIVOICE_PROFILE_DIR` | `--profile-dir` | path | Platform default¹ | Directory for voice cloning profiles. |
| `OMNIVOICE_MAX_REF_AUDIO_MB` | *(env only)* | int (1–200) | `25` | Max upload size for clone reference audio in MB. |

¹ Platform defaults: Linux `~/.local/share/omnivoice/profiles`, macOS `~/Library/Application Support/omnivoice/profiles`

## Examples

```bash
# Run on all interfaces with GPU
OMNIVOICE_HOST=0.0.0.0 OMNIVOICE_DEVICE=cuda omnivoice-server

# Let OS pick a free port and discover it from OMNIVOICE_READY output
OMNIVOICE_PORT=0 omnivoice-server | grep OMNIVOICE_READY

# Deterministic voice output (same voice every request)
OMNIVOICE_POSITION_TEMPERATURE=0 omnivoice-server

# Custom model cache directory
OMNIVOICE_MODEL_CACHE_DIR=/data/models omnivoice-server

# With API key authentication
OMNIVOICE_API_KEY=my-secret-key omnivoice-server
```
