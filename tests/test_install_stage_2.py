from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

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


def test_ensure_runtime_contexts_does_not_provision_bootstrap_context(
    monkeypatch, tmp_path: Path
) -> None:
    bootstrap_context = SimpleNamespace(required_version="3.9")
    runtime_context = SimpleNamespace(
        required_version="3.14",
        base_version="3.14.6",
        environment_name="3.14.6",
    )
    config = SimpleNamespace(bootstrap=bootstrap_context, runtime=runtime_context)
    pyenv_root = tmp_path / "pyenv"
    runtime_python = pyenv_root / "versions" / "3.14.6" / "bin" / "python"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("", encoding="utf-8")
    provisioned_contexts = []
    written_selections = []

    monkeypatch.setattr(
        INSTALL_STAGE_2,
        "load_python_environment_config",
        lambda _repo_root: config,
    )
    monkeypatch.setattr(
        INSTALL_STAGE_2,
        "ensure_minimum_python",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        INSTALL_STAGE_2,
        "default_pyenv_root",
        lambda _user_home: pyenv_root,
    )
    monkeypatch.setattr(
        INSTALL_STAGE_2,
        "ensure_pyenv_installed",
        lambda root, _runner: root / "bin" / "pyenv",
    )

    def fake_ensure_context(root, context, _runner):
        assert root == pyenv_root
        provisioned_contexts.append(context)
        return context.environment_name

    monkeypatch.setattr(INSTALL_STAGE_2, "ensure_pyenv_context", fake_ensure_context)
    monkeypatch.setattr(
        INSTALL_STAGE_2,
        "write_python_version_file",
        lambda _root, selection: written_selections.append(selection),
    )

    result = INSTALL_STAGE_2.ensure_runtime_contexts(tmp_path)

    assert result == (pyenv_root, "3.14.6", runtime_python)
    assert provisioned_contexts == [runtime_context]
    assert written_selections == ["3.14.6"]


def test_resolve_user_home_rejects_implicit_assistant_home(
    monkeypatch, tmp_path: Path
) -> None:
    assistant_home = tmp_path / ".codex-home"
    assistant_home.mkdir()
    monkeypatch.setattr(INSTALL_STAGE_2.Path, "home", lambda: assistant_home)

    try:
        INSTALL_STAGE_2.resolve_user_home(None)
    except RuntimeError as error:
        assert "isolated assistant environment" in str(error)
        assert "--user-home" in str(error)
    else:
        raise AssertionError("implicit assistant home should fail closed")


def test_resolve_user_home_accepts_explicit_absolute_path(tmp_path: Path) -> None:
    assert INSTALL_STAGE_2.resolve_user_home(tmp_path) == tmp_path.resolve()


def test_resolve_user_home_rejects_relative_path() -> None:
    try:
        INSTALL_STAGE_2.resolve_user_home(Path("relative-home"))
    except RuntimeError as error:
        assert "absolute path" in str(error)
    else:
        raise AssertionError("relative --user-home should fail")


def test_user_scoped_paths_share_selected_home(tmp_path: Path) -> None:
    assert (
        INSTALL_STAGE_2.standard_install_venv_path(
            INSTALL_STAGE_2.USER_SCOPE,
            tmp_path,
        )
        == tmp_path / ".local" / "share" / "mdview" / "venv"
    )
    assert (
        INSTALL_STAGE_2.launcher_dir_for_scope(
            INSTALL_STAGE_2.USER_SCOPE,
            tmp_path,
        )
        == tmp_path / ".local" / "bin"
    )
