from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "scripts" / "install_git_hooks.py"


def _run_installer(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INSTALLER), "--repo-root", str(repo_root)],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_install_git_hooks_creates_pre_commit_with_entropy_check(
    tmp_path: Path,
) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)

    result = _run_installer(tmp_path)

    assert result.returncode == 0
    pre_commit = hooks_dir / "pre-commit"
    pre_push = hooks_dir / "pre-push"

    pre_commit_content = pre_commit.read_text(encoding="utf-8")
    pre_push_content = pre_push.read_text(encoding="utf-8")
    assert "mdview entropy pre-commit" in pre_commit_content
    assert "run_tool_with_timeout.py entropy_check" in pre_commit_content
    assert "mdview quality gate pre-push" in pre_push_content
    assert "run_quality_gate_cached.py" in pre_push_content

    assert bool(pre_commit.stat().st_mode & stat.S_IXUSR)
    assert bool(pre_push.stat().st_mode & stat.S_IXUSR)


def test_install_git_hooks_preserves_existing_script_and_appends_block(
    tmp_path: Path,
) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    hook = hooks_dir / "pre-commit"
    hook.write_text("#!/usr/bin/env bash\necho existing\n", encoding="utf-8")
    os.chmod(hook, 0o755)

    result = _run_installer(tmp_path)

    assert result.returncode == 0
    local_hook = hooks_dir / "pre-commit.local"
    assert local_hook.exists()
    assert "echo existing" in local_hook.read_text(encoding="utf-8")

    updated = hook.read_text(encoding="utf-8")
    assert "mdview entropy pre-commit" in updated
    assert ".git/hooks/pre-commit.local" in updated

    rerun = _run_installer(tmp_path)
    assert rerun.returncode == 0
    second = hook.read_text(encoding="utf-8")
    assert second.count("mdview entropy pre-commit") == 2


def test_install_git_hooks_wraps_non_shell_existing_hook(tmp_path: Path) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    hook = hooks_dir / "pre-push"
    hook.write_text("#!/usr/bin/env python3\nprint('legacy')\n", encoding="utf-8")
    os.chmod(hook, 0o755)

    result = _run_installer(tmp_path)

    assert result.returncode == 0
    local_hook = hooks_dir / "pre-push.local"
    assert local_hook.exists()
    assert "print('legacy')" in local_hook.read_text(encoding="utf-8")

    wrapper = hook.read_text(encoding="utf-8")
    assert "mdview quality gate pre-push" in wrapper
    assert ".git/hooks/pre-push.local" in wrapper
