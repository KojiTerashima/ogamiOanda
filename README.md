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

## Running

```bash
poetry run python main_exe.py
```

## Tests

```bash
poetry run pytest
```

## Linting

```bash
poetry run ruff check .
```
