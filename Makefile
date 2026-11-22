PY ?= .venv/bin/python
BIN := $(dir $(PY))

.PHONY: install lint format test cov demo graph check clean

install:
	$(or $(PYTHON),python3) -m venv .venv
	$(BIN)pip install -e ".[dev]"

lint:
	$(BIN)ruff check .
	$(BIN)ruff format --check .

format:
	$(BIN)ruff format .
	$(BIN)ruff check --fix .

test:
	$(BIN)pytest

cov:
	$(BIN)pytest --cov --cov-report=term-missing

demo:
	$(BIN)cross-exam demo

graph:
	$(PY) scripts/gen_graph.py

check: lint test
	$(PY) scripts/gen_graph.py --check

clean:
	rm -rf .cross-exam .pytest_cache .ruff_cache .coverage dist build
