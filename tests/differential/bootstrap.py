from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .constants import (
    BASELINE_COMMIT,
    BASELINE_TREE,
    REQUIRED_BASELINE_FILES,
    REQUIRED_BASELINE_SYMBOL_SNIPPETS,
)


class BaselineContractError(RuntimeError):
    pass


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise BaselineContractError(
            f"git command failed: git -C {repo_root} {' '.join(args)}\n{completed.stderr.strip()}"
        )
    return completed.stdout


def verify_baseline_contract(repo_root: Path) -> dict[str, Any]:
    _git(repo_root, "cat-file", "-e", f"{BASELINE_COMMIT}^{{commit}}")
    commit = _git(repo_root, "rev-parse", f"{BASELINE_COMMIT}^{{commit}}").strip()
    if commit != BASELINE_COMMIT:
        raise BaselineContractError(f"commit mismatch: expected {BASELINE_COMMIT}, got {commit}")

    tree = _git(repo_root, "rev-parse", f"{BASELINE_COMMIT}^{{tree}}").strip()
    if tree != BASELINE_TREE:
        raise BaselineContractError(f"tree mismatch: expected {BASELINE_TREE}, got {tree}")

    file_list = set(_git(repo_root, "ls-tree", "-r", "--name-only", BASELINE_COMMIT).splitlines())
    missing_files = [path for path in REQUIRED_BASELINE_FILES if path not in file_list]
    if missing_files:
        raise BaselineContractError(f"baseline missing required files: {missing_files}")

    symbols: dict[str, list[str]] = {}
    for path, snippets in REQUIRED_BASELINE_SYMBOL_SNIPPETS.items():
        source = _git(repo_root, "show", f"{BASELINE_COMMIT}:{path}")
        file_symbols = []
        for snippet in snippets:
            if snippet not in source:
                raise BaselineContractError(f"missing required symbol snippet in {path}: {snippet}")
            file_symbols.append(snippet)
        symbols[path] = file_symbols

    return {
        "baseline_commit": BASELINE_COMMIT,
        "baseline_tree": BASELINE_TREE,
        "required_files": list(REQUIRED_BASELINE_FILES),
        "symbols": symbols,
    }


def dump_baseline_contract(path: Path, contract: dict[str, Any]) -> None:
    path.write_text(json.dumps(contract, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
