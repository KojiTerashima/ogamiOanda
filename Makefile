# Quality gate commands for ogamiOanda
# Usage: make check   (lint + test)
#        make lint
#        make test

PYTHON := .venv/bin/python

.PHONY: check lint test

check: lint test

lint:
	$(PYTHON) -m ruff check .

test:
	$(PYTHON) -m pytest -q tests
