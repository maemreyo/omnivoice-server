PY ?= python3.11

.PHONY: help install dev test test-cov lint format type-check clean build publish docs docker-build docker-run

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install package with basic dependencies
	$(PY) -m pip install -e .

dev: ## Install package with development dependencies
	$(PY) -m pip install -e ".[dev]"

test: ## Run tests
	$(PY) -m pytest tests/ -v

test-cov: ## Run tests with coverage report
	$(PY) -m pytest tests/ -v --cov=omnivoice_server --cov-report=term-missing --cov-report=html

lint: ## Run linting with ruff
	ruff check omnivoice_server/ tests/

format: ## Format code with ruff
	ruff format omnivoice_server/ tests/

type-check: ## Run type checking with mypy
	mypy omnivoice_server/

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .mypy_cache/ .ruff_cache/ htmlcov/ .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

build: ## Build package wheel and sdist
	$(PY) -m build

publish-test: ## Publish to TestPyPI (for testing)
	$(PY) -m twine upload --repository testpypi dist/*

publish: ## Publish to PyPI (requires authentication token)
	$(PY) -m twine upload dist/*

docker-build: ## Build Docker image
	docker build -t omnivoice-server:latest .

docker-run: ## Run Docker container
	docker run -d -p 8880:8880 -v $(PWD)/profiles:/app/profiles --name omnivoice omnivoice-server:latest

docker-stop: ## Stop Docker container
	docker stop omnivoice && docker rm omnivoice

pre-commit-install: ## Install pre-commit hooks
	pre-commit install

pre-commit-run: ## Run pre-commit hooks on all files
	pre-commit run --all-files
