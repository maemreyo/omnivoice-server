## CLI Usage

```bash
# Start server with defaults
omnivoice-server

# Custom host and port
omnivoice-server --host 0.0.0.0 --port 8880

# Use GPU
omnivoice-server --device cuda

# Adjust inference quality (higher = better quality, slower)
omnivoice-server --num-step 32

# Enable authentication
omnivoice-server --api-key your-secret-key

# Adjust concurrency
omnivoice-server --max-concurrent 4

# Custom model path
omnivoice-server --model-id /path/to/local/model
```

### Environment Variables

All CLI options can be set via environment variables with `OMNIVOICE_` prefix:

```bash
export OMNIVOICE_HOST=0.0.0.0
export OMNIVOICE_PORT=8880
export OMNIVOICE_DEVICE=cuda
export OMNIVOICE_API_KEY=your-secret-key
export OMNIVOICE_NUM_STEP=32
export OMNIVOICE_MAX_CONCURRENT=4

omnivoice-server
```
