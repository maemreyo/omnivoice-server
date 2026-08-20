# Runbook — Common Issues

## 1. Port Conflict

**Symptom:** Server exits immediately with `[Errno 48] Address already in use` or `[Errno 98]`.

**Cause:** Another process is already using port 8880.

**Resolution:**
```bash
# Find what's using the port
lsof -i :8880          # macOS/Linux
ss -tlnp | grep 8880   # Linux alternative

# Option A: Use a different port
OMNIVOICE_PORT=9000 omnivoice-server

# Option B: Let OS assign an available port
OMNIVOICE_PORT=0 omnivoice-server
# Read the assigned port from stdout: OMNIVOICE_READY host=127.0.0.1 port=XXXXX
```

---

## 2. Model Download Failure

**Symptom:** Server hangs or exits during startup with HuggingFace download error.

**Cause A — Network issue:**
```
requests.exceptions.ConnectionError: HTTPSConnectionPool(host='huggingface.co', ...)
```
**Resolution:** Check network connectivity. If behind a proxy: `export HTTPS_PROXY=http://proxy:port`.

**Cause B — Disk space:**
```
OSError: [Errno 28] No space left on device
```
**Resolution:**
```bash
df -h ~/.cache/huggingface   # Check available space (need ~3 GB)
OMNIVOICE_MODEL_CACHE_DIR=/path/with/space omnivoice-server
```

**Cause C — Partial download (corrupt cache):**
```bash
rm -rf ~/.cache/huggingface/hub/models--k2-fsa--OmniVoice
omnivoice-server   # Re-download from scratch
```

---

## 3. Inference Fails After Startup (Low RAM / OOM)

**Symptom:** Server starts, model loads, but synthesis requests return 500. System may become unresponsive.

**Cause:** Available RAM too low. Model needs ~1.7 GB; requests need additional working memory.

**Diagnosis:**
```bash
# Check /health for current memory usage
curl http://localhost:8880/health | python3 -m json.tool
# Look at: memory_rss_mb

# Check system memory
free -h   # Linux
vm_stat   # macOS
```

**Resolution:**
- Minimum 8 GB RAM recommended. Close other applications.
- On systems with <8 GB, reduce `OMNIVOICE_MAX_CONCURRENT=1`.
- Check system logs for OOM killer: `dmesg | grep -i "killed process"` (Linux).

---

## 4. Profile Storage Permission Denied

**Symptom:** Creating or loading voice profiles fails with 500. Logs show:
```
PermissionError: [Errno 13] Permission denied: '/path/to/profiles'
```

**Cause:** Server cannot write to the profiles directory.

**Resolution:**
```bash
# Check current profiles directory
curl http://localhost:8880/health | python3 -m json.tool

# Option A: Fix permissions on default directory
mkdir -p ~/.local/share/omnivoice/profiles   # Linux
chmod 755 ~/.local/share/omnivoice/profiles

# Option B: Use a custom writable directory
OMNIVOICE_PROFILE_DIR=/tmp/omnivoice-profiles omnivoice-server
```

---

## 5. Server Not Ready (Health Returns 503)

**Symptom:** Requests to `/v1/audio/speech` return 503 immediately after server starts.

**Cause:** Model is still loading. This is normal — the model takes 10–60 seconds to load.

**Resolution:** Poll `/health` until it returns HTTP 200 with `ready: true`:
```bash
until curl -sf http://localhost:8880/health | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ready') else 1)"; do
  echo "Waiting for server..."
  sleep 2
done
echo "Server ready!"
```
