from __future__ import annotations

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-baseline-replay",
        action="store_true",
        default=False,
        help="Run slow baseline replay tests that execute the legacy commit in a detached worktree.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-baseline-replay"):
        return
    skip = pytest.mark.skip(reason="requires --run-baseline-replay")
    for item in items:
        if "baseline_replay" in item.keywords:
            item.add_marker(skip)
