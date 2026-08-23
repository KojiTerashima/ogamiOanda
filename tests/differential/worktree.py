from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .constants import BASELINE_COMMIT, BASELINE_TREE


class WorktreeError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitIdentity:
    commit: str
    tree: str


@dataclass(frozen=True)
class WorktreeInfo:
    repo_root: Path
    worktree_path: Path
    baseline: GitIdentity


def _git(repo_root: Path, *args: str) -> str:
    command = ["git", "-C", str(repo_root), *args]
    env = os.environ.copy()
    env.setdefault("GIT_CONFIG_GLOBAL", "/dev/null")
    env.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        raise WorktreeError(
            f"git command failed: {' '.join(command)}\n{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def verify_baseline_reference(repo_root: Path, *, commit: str = BASELINE_COMMIT) -> GitIdentity:
    _git(repo_root, "cat-file", "-e", f"{commit}^{{commit}}")
    resolved_commit = _git(repo_root, "rev-parse", f"{commit}^{{commit}}")
    if resolved_commit != commit:
        raise WorktreeError(
            f"Baseline commit mismatch: expected {commit}, got {resolved_commit}"
        )
    resolved_tree = _git(repo_root, "rev-parse", f"{commit}^{{tree}}")
    if resolved_tree != BASELINE_TREE:
        raise WorktreeError(
            f"Baseline tree mismatch: expected {BASELINE_TREE}, got {resolved_tree}"
        )
    return GitIdentity(commit=resolved_commit, tree=resolved_tree)


def worktree_is_clean(worktree_path: Path) -> bool:
    status = _git(worktree_path, "status", "--porcelain")
    return status == ""


def assert_worktree_clean(worktree_path: Path, *, reason: str) -> None:
    if not worktree_is_clean(worktree_path):
        status = _git(worktree_path, "status", "--porcelain")
        raise WorktreeError(f"Worktree not clean ({reason}):\n{status}")


def assert_worktree_head(worktree_path: Path, expected_commit: str) -> None:
    head = _git(worktree_path, "rev-parse", "HEAD")
    if head != expected_commit:
        raise WorktreeError(f"Worktree HEAD mismatch: expected {expected_commit}, got {head}")


@contextlib.contextmanager
def baseline_worktree(repo_root: Path, *, commit: str = BASELINE_COMMIT):
    baseline = verify_baseline_reference(repo_root, commit=commit)
    with tempfile.TemporaryDirectory(prefix="ogami-baseline-worktree-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        worktree_path = tmp_path / "baseline"
        _git(repo_root, "worktree", "add", "--detach", str(worktree_path), baseline.commit)
        body_error: BaseException | None = None
        try:
            assert_worktree_head(worktree_path, baseline.commit)
            assert_worktree_clean(worktree_path, reason="after creation")
            yield WorktreeInfo(repo_root=repo_root, worktree_path=worktree_path, baseline=baseline)
        except BaseException as error:
            body_error = error
            raise
        finally:
            try:
                assert_worktree_head(worktree_path, baseline.commit)
                assert_worktree_clean(worktree_path, reason="before cleanup")
            except WorktreeError as verification_error:
                if body_error is None:
                    raise
                body_error.add_note(
                    f"legacy worktree exit verification also failed: {verification_error}"
                )
            finally:
                with contextlib.suppress(WorktreeError):
                    _git(
                        repo_root,
                        "worktree",
                        "remove",
                        "--force",
                        str(worktree_path),
                    )
