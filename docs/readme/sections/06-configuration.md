## Configuration

| Option | Env Var | Default | Description |
|--------|---------|---------|-------------|
| `--host` | `OMNIVOICE_HOST` | `127.0.0.1` | Bind host |
| `--port` | `OMNIVOICE_PORT` | `8880` | Bind port |
| `--device` | `OMNIVOICE_DEVICE` | `cpu` | Device: cpu, cuda (MPS broken) |
| `--num-step` | `OMNIVOICE_NUM_STEP` | `32` | Inference steps (1-64, higher=better quality) |
| `--max-concurrent` | `OMNIVOICE_MAX_CONCURRENT` | `2` | Max concurrent requests |
| `--api-key` | `OMNIVOICE_API_KEY` | `""` | Bearer token (empty = no auth) |
| `--cors-origins` | `OMNIVOICE_CORS_ALLOW_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000,http://localhost:5001,http://127.0.0.1:5001,http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowed browser origins |
| `--cors-allow-credentials` | `OMNIVOICE_CORS_ALLOW_CREDENTIALS` | `false` | Allow credentialed CORS requests; requires explicit origins |
| `--model-id` | `OMNIVOICE_MODEL_ID` | `k2-fsa/OmniVoice` | HuggingFace repo or local path |
| `--profile-dir` | `OMNIVOICE_PROFILE_DIR` | `~/.omnivoice/profiles` | Voice profiles directory |
| `--log-level` | `OMNIVOICE_LOG_LEVEL` | `info` | Logging level |

### CORS Notes

- Browser frontends on a different origin (for example `http://localhost:5001`) require CORS.
- `--cors-origins` accepts a comma-separated list or the equivalent env var value.
- Do **not** combine `--cors-allow-credentials` with a wildcard origin (`*`).

Example:

```bash
omnivoice-server --cors-origins "http://localhost:5001,http://localhost:5173"
```
