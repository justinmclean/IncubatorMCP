PYTHON ?= python3

.PHONY: help install install-dev format lint check-format typecheck test coverage check clean

help:
	@echo "Available targets:"
	@echo "  install      Install the package"
	@echo "  install-dev  Install package with dev dependencies"
	@echo "  format       Run code formatters"
	@echo "  lint         Run linters"
	@echo "  check-format Check formatting without changing files"
	@echo "  typecheck    Run mypy"
	@echo "  test         Run unit tests"
	@echo "  coverage     Run tests with coverage"
	@echo "  check        Run lint, typecheck, and tests"
	@echo "  clean        Remove caches and coverage artifacts"

install:
	$(PYTHON) -m pip install -e .

install-dev:
	$(PYTHON) -m pip install -e .[dev]

format:
	$(PYTHON) -m ruff format ipmc tests server.py

check-format:
	$(PYTHON) -m ruff format --check ipmc tests server.py

lint:
	$(PYTHON) -m ruff check ipmc tests server.py

typecheck:
	$(PYTHON) -m mypy ipmc tests

test:
	$(PYTHON) -m unittest discover -s tests -v

coverage:
	$(PYTHON) -m coverage run --branch -m unittest discover -s tests
	$(PYTHON) -m coverage report -m

check: lint typecheck test

clean:
	rm -rf .coverage .mypy_cache .ruff_cache htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
