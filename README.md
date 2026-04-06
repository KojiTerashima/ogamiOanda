# ogamiOanda

Python-based automated trading system using the Oanda v20 REST API.

## Requirements

- Python 3.11+
- [Poetry](https://python-poetry.org/)

## Setup

```bash
# 1. Install dependencies
poetry install

# 2. Create local configuration
cp settings.example.yaml settings.yaml

# 3. Fill in credentials and paths
#    (see docs/configuration.md for details)
```

## Configuration

Runtime settings are loaded from `settings.yaml` (ignored by git).  
See [docs/configuration.md](docs/configuration.md) for the full setup guide,
required keys, and troubleshooting.

Issue/PR template examples for the current refactoring backlog are available at
[docs/issue_pr_templates.md](docs/issue_pr_templates.md).

## Running

```bash
poetry run python main_exe.py
```

## Quality Gate

Run lint and tests together with:

```bash
make check
```

Or individually:

```bash
make lint   # ruff check .
make test   # pytest -q tests
```

Both commands use the local `.venv` created by `poetry install`.

## Tests

```bash
make test
# or: .venv/bin/python -m pytest -q tests
```

## Linting

```bash
make lint
# or: .venv/bin/python -m ruff check .
```
