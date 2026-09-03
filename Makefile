.DEFAULT_GOAL := help
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help bootstrap ingest dev test audit lint verify report reset

help:  ## show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-12s %s\n", $$1, $$2}'

bootstrap:  ## create the virtualenv and install the project
	python3 -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e ".[dev]"

ingest:  ## rebuild the database from data/raw/ (raw files are never written to)
	$(PY) -m halyard.cli ingest

reset:  ## delete the built database
	$(PY) -m halyard.cli reset

report:  ## show what the current database was built from
	$(PY) -m halyard.cli report

dev:  ## run the API at http://127.0.0.1:8000 (docs at /docs)
	$(VENV)/bin/uvicorn halyard.api.asgi:app --reload --port 8000

test:  ## run every test (application + forensic audit)
	$(PY) -m pytest -q

audit:  ## re-run the forensic audit over data/raw/
	$(PY) analysis/audit/run_audit.py

lint:  ## style check
	$(VENV)/bin/flake8 halyard analysis tests

verify: lint reset ingest test audit  ## clean rebuild, full test suite and audit parity
	@echo "verify: clean rebuild, tests and audit all passed"
