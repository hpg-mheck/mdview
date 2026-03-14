from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMMIT_PUSH = ROOT / "scripts" / "git_standard_commit_push.py"
VETERAN_PULL = ROOT / "scripts" / "git_veteran_pull.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_git_standard_commit_push_rejects_missing_message() -> None:
    result = _run(COMMIT_PUSH)
    assert result.returncode == 2


def test_git_veteran_pull_rejects_branch_without_remote() -> None:
    result = _run(VETERAN_PULL, "--branch", "trunk")
    assert result.returncode == 1
    assert "--branch requires --remote." in result.stderr


def test_git_standard_commit_push_dry_run_succeeds() -> None:
    result = _run(COMMIT_PUSH, "--dry-run", "-m", "test message")
    assert result.returncode == 0
