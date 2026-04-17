## Configuration

| Option | Env Var | Default | Description |
|--------|---------|---------|-------------|
| `--host` | `OMNIVOICE_HOST` | `127.0.0.1` | Bind host |
| `--port` | `OMNIVOICE_PORT` | `8880` | Bind port |
| `--device` | `OMNIVOICE_DEVICE` | `cpu` | Device: cpu, cuda (MPS broken) |
| `--num-step` | `OMNIVOICE_NUM_STEP` | `32` | Inference steps (1-64, higher=better quality) |
| `--max-concurrent` | `OMNIVOICE_MAX_CONCURRENT` | `2` | Max concurrent requests |
| `--api-key` | `OMNIVOICE_API_KEY` | `""` | Bearer token (empty = no auth) |
| `--model-id` | `OMNIVOICE_MODEL_ID` | `k2-fsa/OmniVoice` | HuggingFace repo or local path |
| `--profile-dir` | `OMNIVOICE_PROFILE_DIR` | `~/.omnivoice/profiles` | Voice profiles directory |
| `--log-level` | `OMNIVOICE_LOG_LEVEL` | `info` | Logging level |
