## Development

### Setup

```bash
# Clone repository
git clone https://github.com/maemreyo/omnivoice-server.git
cd omnivoice-server

# Install with dev dependencies
pip install -e ".[dev]"
```

### Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=omnivoice_server --cov-report=term-missing

# Run specific test
pytest tests/test_streaming.py -v
```

### Code Quality

```bash
# Lint
ruff check omnivoice_server/ tests/

# Format
ruff format omnivoice_server/ tests/

# Type check
mypy omnivoice_server/
```

### CI/CD

GitHub Actions workflow runs on every push:
- Linting (ruff)
- Type checking (mypy)
- Tests (pytest)
- Python 3.10, 3.11, 3.12
