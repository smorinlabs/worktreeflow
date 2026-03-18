.PHONY: test lint format typecheck coverage build clean help completions-bash completions-zsh completions-fish version bump-patch bump-minor bump-major release

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

test: ## Run tests
	uv run pytest tests/ -v --tb=short

lint: ## Run linting checks
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

format: ## Auto-format code
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

typecheck: ## Run type checking
	uv run ty check src/worktreeflow/

coverage: ## Run tests with coverage report
	uv run pytest tests/ --cov=worktreeflow --cov-report=term-missing --cov-fail-under=35

build: ## Build the package
	uv build

clean: ## Remove build artifacts
	rm -rf dist/ build/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true

version: ## Show current version
	@uv run python -c "from importlib.metadata import version; print(version('worktreeflow'))"

bump-patch: ## Bump patch version (e.g. 0.3.0 → 0.3.1)
	@uv run python scripts/bump_version.py patch

bump-minor: ## Bump minor version (e.g. 0.3.0 → 0.4.0)
	@uv run python scripts/bump_version.py minor

bump-major: ## Bump major version (e.g. 0.3.0 → 1.0.0)
	@uv run python scripts/bump_version.py major

release: ## Sync, commit, tag (run make bump-* first)
	@uv sync; \
	VERSION=$$(uv run python -c "from importlib.metadata import version; print(version('worktreeflow'))"); \
	git add pyproject.toml; \
	git commit -m "chore: bump version to $$VERSION"; \
	git tag "v$$VERSION"; \
	echo ""; \
	echo "Created tag v$$VERSION."; \
	echo "Run 'git push && git push --tags' to publish."

completions-bash: ## Generate bash completions
	_WTF_COMPLETE=bash_source uv run wtf

completions-zsh: ## Generate zsh completions
	_WTF_COMPLETE=zsh_source uv run wtf

completions-fish: ## Generate fish completions
	_WTF_COMPLETE=fish_source uv run wtf
