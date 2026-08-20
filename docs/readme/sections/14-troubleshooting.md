## Troubleshooting

### Model Download Issues

The model is downloaded from HuggingFace on first run. If you encounter issues:

```bash
# Pre-download the model
python -c "from omnivoice import OmniVoice; OmniVoice.from_pretrained('k2-fsa/OmniVoice')"

# Or use a local model
omnivoice-server --model-id /path/to/local/model
```

### CUDA Out of Memory

Reduce concurrent requests or use CPU:

```bash
omnivoice-server --max-concurrent 1 --device cpu
```

### Audio Quality Issues

Increase inference steps for better quality:

```bash
omnivoice-server --num-step 32
```

### Windows Voice Cloning Fails with `libtorchcodec`

If voice cloning fails during auto-transcription on Windows with an error like
`RuntimeError: Could not load libtorchcodec`, the usual cause is an incompatible
`torchcodec` installation.

Short-term project behavior:

- the default dev extra no longer installs `torchcodec` on Windows
- auto-transcription now fails with a clearer error instead of an opaque `500`
- voice cloning still works if you provide `ref_text` explicitly

Recommended paths:

```bash
# Path 1: skip auto-transcription and provide ref_text yourself
curl -X POST http://127.0.0.1:8880/v1/audio/speech/clone \
  -F "input=Hello world" \
  -F "file=@ref.wav" \
  -F "ref_text=Reference transcript"
```

```bash
# Path 2: if you want auto-transcription on Windows, keep torch/torchaudio/torchcodec aligned
pip install torchcodec==0.11.1
pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu128 --upgrade
```

If you already have a working local workaround, you can keep using it. This repo fix
is meant to make the default Windows path fail more safely and avoid pulling in an
unhelpful torchcodec install through the dev extra.

### Browser CORS Errors

If `curl` works but a browser frontend fails with a CORS error, the frontend and server are running on different origins and the browser is blocking the request.

Start the server with the frontend origin explicitly allowed:

```bash
omnivoice-server --cors-origins "http://localhost:5001"
```

#### Manual Smoke Test: Preflight

Verify that browser preflight succeeds:

```bash
curl -i -X OPTIONS http://127.0.0.1:8880/v1/audio/speech \
  -H "Origin: http://localhost:5001" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type,Authorization"
```

Expected result:

- HTTP status `200`
- `Access-Control-Allow-Origin: http://localhost:5001`
- `Access-Control-Allow-Methods` includes `POST`

#### Manual Smoke Test: Actual Request

```bash
curl -i -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H "Origin: http://localhost:5001" \
  -H "Content-Type: application/json" \
  -d '{"model":"omnivoice","input":"Hello from browser smoke test","voice":"auto"}' \
  --output /tmp/omnivoice-smoke.wav
```

Expected result:

- HTTP status `200`
- `Access-Control-Allow-Origin: http://localhost:5001`
- audio file written successfully

#### Manual Smoke Test: Auth + CORS

If API key auth is enabled, preflight should still succeed and failed auth responses should still include CORS headers for allowed origins:

```bash
omnivoice-server --api-key secret-token --cors-origins "http://localhost:5001"
```

```bash
curl -i -X OPTIONS http://127.0.0.1:8880/v1/audio/speech \
  -H "Origin: http://localhost:5001" \
  -H "Access-Control-Request-Method: POST"
```

```bash
curl -i -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H "Origin: http://localhost:5001" \
  -H "Content-Type: application/json" \
  -d '{"model":"omnivoice","input":"Missing auth should still be CORS-visible","voice":"auto"}'
```

Expected result:

- Preflight returns `200`
- Unauthorized POST returns `401`
- Unauthorized response still includes `Access-Control-Allow-Origin` for the allowed origin
