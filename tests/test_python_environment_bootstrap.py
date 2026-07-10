"""Regression coverage for user-owned pyenv bootstrap boundaries."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "python_environment_bootstrap_under_test",
    ROOT / "scripts" / "python_environment_bootstrap.py",
)
assert SPEC is not None and SPEC.loader is not None
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BOOTSTRAP
SPEC.loader.exec_module(BOOTSTRAP)


class RunRecorder:
    """Record subprocess commands without touching a real pyenv checkout."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs) -> subprocess.CompletedProcess:
        normalized = [str(part) for part in command]
        self.commands.append(normalized)
        return subprocess.CompletedProcess(normalized, returncode=0)


def test_existing_pyenv_checkout_is_reused_without_git_mutation(tmp_path: Path) -> None:
    pyenv_root = tmp_path / "pyenv"
    executable = pyenv_root / "bin" / "pyenv"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    recorder = RunRecorder()

    result = BOOTSTRAP.ensure_pyenv_installed(pyenv_root, recorder)

    assert result == executable
    assert recorder.commands == []


def test_missing_pyenv_checkout_is_cloned_at_reviewed_release(tmp_path: Path) -> None:
    pyenv_root = tmp_path / "pyenv"
    recorder = RunRecorder()

    BOOTSTRAP.ensure_pyenv_installed(pyenv_root, recorder)

    assert recorder.commands == [
        [
            "git",
            "clone",
            "--branch",
            BOOTSTRAP.PYENV_RELEASE,
            "--depth",
            "1",
            BOOTSTRAP.PYENV_REPO,
            str(pyenv_root),
        ]
    ]


def test_existing_pyenv_plugin_is_reused_without_git_mutation(tmp_path: Path) -> None:
    pyenv_root = tmp_path / "pyenv"
    plugin_root = pyenv_root / "plugins" / "pyenv-virtualenv"
    plugin_root.mkdir(parents=True)
    recorder = RunRecorder()

    result = BOOTSTRAP.ensure_pyenv_virtualenv_plugin(pyenv_root, recorder)

    assert result == plugin_root
    assert recorder.commands == []


def test_missing_pyenv_plugin_is_cloned_at_reviewed_release(tmp_path: Path) -> None:
    pyenv_root = tmp_path / "pyenv"
    plugin_root = pyenv_root / "plugins" / "pyenv-virtualenv"
    recorder = RunRecorder()

    BOOTSTRAP.ensure_pyenv_virtualenv_plugin(pyenv_root, recorder)

    assert recorder.commands == [
        [
            "git",
            "clone",
            "--branch",
            BOOTSTRAP.PYENV_PLUGIN_RELEASE,
            "--depth",
            "1",
            BOOTSTRAP.PYENV_PLUGIN_REPO,
            str(plugin_root),
        ]
    ]
