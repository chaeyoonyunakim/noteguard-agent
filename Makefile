# NoteGuard Agent -- common developer tasks.
# Usage: `make <target>`. Run `make help` to list targets.

.DEFAULT_GOAL := help
PYTHON ?= python
SRC := src agent app eval

.PHONY: help install install-dev lint format test coverage data run eval clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime dependencies
	$(PYTHON) -m pip install -e .

install-dev: ## Install development dependencies and pre-commit hooks
	$(PYTHON) -m pip install -e ".[dev]"
	pre-commit install

lint: ## Run ruff lint + format checks
	ruff check $(SRC) tests
	ruff format --check $(SRC) tests

format: ## Auto-format and fix lint with ruff
	ruff check --fix $(SRC) tests
	ruff format $(SRC) tests

test: ## Run the unit test suite
	$(PYTHON) -m pytest

coverage: ## Run tests with a coverage report
	$(PYTHON) -m pytest --cov=src --cov-report=term-missing

data: ## Download synthetic dataset CSVs into data/ (run once)
	$(PYTHON) src/fetch_dataset.py

run: ## Run the clinician web UI locally (http://localhost:8000)
	uvicorn app.api:app --reload --port 8000

eval: ## Run LangSmith evaluations
	$(PYTHON) -m eval.run_eval

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
