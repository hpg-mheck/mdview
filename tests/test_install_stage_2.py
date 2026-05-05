from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "install_stage_2",
    ROOT / "scripts" / "install-stage-2.py",
)
assert SPEC is not None and SPEC.loader is not None
INSTALL_STAGE_2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL_STAGE_2)


class RunRecorder:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs) -> subprocess.CompletedProcess:
        self.commands.append([str(part) for part in command])
        return subprocess.CompletedProcess(command, returncode=0)


def test_suppress_child_failure_summary_for_install_project() -> None:
    error = subprocess.CalledProcessError(
        1,
        ["/tmp/python", str(ROOT / "scripts" / "install_project.py")],
    )

    assert INSTALL_STAGE_2.suppress_child_failure_summary(error) is True


def test_suppress_child_failure_summary_for_other_failures() -> None:
    error = subprocess.CalledProcessError(
        1,
        ["/tmp/python", "-m", "pip", "install", "."],
    )

    assert INSTALL_STAGE_2.suppress_child_failure_summary(error) is False


def test_install_build_bootstrap_upgrades_pip_and_reports_venv(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    recorder = RunRecorder()
    monkeypatch.setattr(INSTALL_STAGE_2, "run", recorder)
    venv_python = tmp_path / "venv" / "bin" / "python"

    INSTALL_STAGE_2.install_build_bootstrap(venv_python)

    expected_command = [
        str(venv_python),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
        "setuptools>=69",
        "wheel",
    ]
    assert recorder.commands == [expected_command]
    stdout = capsys.readouterr().out
    assert f"Refreshing pip, setuptools, and wheel in {tmp_path / 'venv'}" in stdout
    expected_manual_command = " ".join(
        INSTALL_STAGE_2.shlex.quote(part) for part in expected_command
    )
    assert "Manual update command: " + expected_manual_command in stdout
