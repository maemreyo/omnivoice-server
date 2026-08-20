## Docker Deployment

### Quick Start with Docker Compose

```bash
# Start the server
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the server
docker-compose down
```

The server will be available at `http://localhost:8880`. Voice profiles are persisted in the `./profiles` directory.

### Build and Run Manually

```bash
# Build the image
docker build -t omnivoice-server .

# Run the container
docker run -d \
  -p 8880:8880 \
  -v $(pwd)/profiles:/app/profiles \
  -e OMNIVOICE_API_KEY=your-secret-key \
  --name omnivoice \
  omnivoice-server

# View logs
docker logs -f omnivoice
```

### Configuration

Set environment variables in `docker-compose.yml` or pass them with `-e`:

- `OMNIVOICE_HOST=0.0.0.0` - Bind host (must be 0.0.0.0 in Docker)
- `OMNIVOICE_PORT=8880` - Server port
- `OMNIVOICE_DEVICE=cpu` - Device (cpu, cuda)
- `OMNIVOICE_NUM_STEP=32` - Inference steps
- `OMNIVOICE_API_KEY=secret` - Optional authentication

For CUDA GPU support, see comments in `docker-compose.yml`.
