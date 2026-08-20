PY ?= python3.11

.PHONY: help install dev test test-cov lint format type-check clean build publish docs docker-build docker-run release

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

## Release Commands
.PHONY: release release-patch release-minor release-major
RELEASE_VERSION ?=

release: ## Create a new release (Usage: make release RELEASE_VERSION=0.3.0)
	@if [ -z "$(RELEASE_VERSION)" ]; then \
		echo "❌ Error: RELEASE_VERSION is required"; \
		echo "Usage: make release RELEASE_VERSION=0.3.0"; \
		echo "Or use convenience targets:"; \
		echo "  make release-patch  # 0.2.0 → 0.2.1"; \
		echo "  make release-minor  # 0.2.0 → 0.3.0"; \
		echo "  make release-major  # 0.2.0 → 1.0.0"; \
		exit 1; \
	fi
	@echo "📦 Releasing v$(RELEASE_VERSION)..."
	@echo ""
	@echo "1/6 Updating version in pyproject.toml..."
	sed -i '' 's/^version = ".*"/version = "$(RELEASE_VERSION)"/' pyproject.toml
	@echo "2/6 Updating version in omnivoice_server/__init__.py..."
	sed -i '' 's/^__version__ = ".*"/__version__ = "$(RELEASE_VERSION)"/' omnivoice_server/__init__.py
	@echo "3/6 Committing changes..."
	git add -A
	git commit -m "chore: bump version to $(RELEASE_VERSION)"
	@echo "4/6 Creating git tag..."
	git tag -a v$(RELEASE_VERSION) -m "Release v$(RELEASE_VERSION)"
	@echo "5/6 Pushing to remote..."
	git push origin HEAD:main && git push origin v$(RELEASE_VERSION)
	@echo "6/6 Creating GitHub release..."
	@gh release create v$(RELEASE_VERSION) \
		--title "v$(RELEASE_VERSION)" \
		--notes "See CHANGELOG.md for details."
	@echo ""
	@echo "✅ Release v$(RELEASE_VERSION) created!"
	@echo "   PyPI and Docker workflows will run automatically."

release-patch: ## Release patch version bump (0.2.0 → 0.2.1)
	$(eval NEW_VERSION := $(shell awk -F. '{print $$1"."$$2"."$$3+1}' <<< "$(shell grep '^version = ' pyproject.toml | sed 's/version = "//;s/"//')"))
	@echo "🔧 Current version detected, bumping to patch..."
	@make release RELEASE_VERSION=$(NEW_VERSION)

release-minor: ## Release minor version bump (0.2.0 → 0.3.0)
	$(eval NEW_VERSION := $(shell awk -F. '{print $$1"."$$2+1".0"}' <<< "$(shell grep '^version = ' pyproject.toml | sed 's/version = "//;s/"//')"))
	@echo "🔧 Current version detected, bumping to minor..."
	@make release RELEASE_VERSION=$(NEW_VERSION)

release-major: ## Release major version bump (0.2.0 → 1.0.0)
	$(eval NEW_VERSION := $(shell awk -F. '{print $$1+1".0.0"}' <<< "$(shell grep '^version = ' pyproject.toml | sed 's/version = "//;s/"//')"))
	@echo "🔧 Current version detected, bumping to major..."
	@make release RELEASE_VERSION=$(NEW_VERSION)
