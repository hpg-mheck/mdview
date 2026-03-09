import sys
from pathlib import Path

from scripts.install_prerequisites import (
    CommandRunner,
    OSInfo,
    build_install_commands,
    ensure_virtualenv,
    install_project,
    install_git_hooks,
    parse_os_release,
    resolve_project_root,
    resolve_venv_path,
    select_package_manager,
    system_packages_for,
    venv_python_path,
)


class RecordingRunner(CommandRunner):
    def __init__(self, dry_run: bool = True):
        super().__init__(dry_run=dry_run)
        self.commands = []
        self.cwds = []

    def run(self, command, cwd=None):
        self.commands.append(list(command))
        self.cwds.append(cwd)
        super().run(command, cwd=cwd)


def test_parse_os_release_handles_quotes_and_comments():
    content = """
NAME="Ubuntu"
VERSION_ID="24.04"
# Comment
ID=ubuntu
"""
    parsed = parse_os_release(content)
    assert parsed["NAME"] == "Ubuntu"
    assert parsed["VERSION_ID"] == "24.04"
    assert parsed["ID"] == "ubuntu"


def test_select_package_manager_prefers_distribution_default():
    os_info = OSInfo(platform_id="ubuntu", version_id="24.04", pretty_name="Ubuntu")
    manager = select_package_manager(os_info, available=["apt-get", "dnf"])
    assert manager == "apt-get"


def test_select_package_manager_falls_back_to_available_option():
    os_info = OSInfo(platform_id="rocky", version_id="9.6", pretty_name="Rocky Linux")
    manager = select_package_manager(os_info, available=["yum"])
    assert manager == "yum"


def test_select_package_manager_returns_none_for_windows():
    os_info = OSInfo(platform_id="windows", version_id="11", pretty_name="Windows 11")
    manager = select_package_manager(os_info, available=["winget"])
    assert manager is None


def test_build_install_commands_adds_sudo_prefix():
    commands = build_install_commands(
        manager="apt-get",
        packages=["python3"],
        use_sudo=True,
    )
    assert commands[0][0] == "sudo"
    assert commands[1][:3] == ["sudo", "apt-get", "-y"]


def test_system_packages_for_fedora_like_systems():
    packages = system_packages_for("dnf")
    assert "python3-virtualenv" in packages
    assert "less" in packages


def test_ensure_virtualenv_requests_creation_when_missing(tmp_path: Path):
    venv_path = tmp_path / "venv"
    runner = RecordingRunner()
    created_python = ensure_virtualenv(sys.executable, venv_path, runner)
    expected_python = venv_path / "bin" / "python"
    assert created_python == expected_python
    assert runner.commands[0][:3] == [sys.executable, "-m", "venv"]


def test_venv_python_path_uses_windows_layout(monkeypatch, tmp_path: Path):
    import scripts.install_prerequisites as installer

    monkeypatch.setattr(installer.os, "name", "nt")
    path = venv_python_path(tmp_path / ".venv")
    assert path == tmp_path / ".venv" / "Scripts" / "python.exe"


def test_install_git_hooks_runs_hook_installer_with_selected_python():
    runner = RecordingRunner()
    repo_root = Path("/tmp/repo-root")

    install_git_hooks(sys.executable, runner, repo_root)

    command = runner.commands[0]
    assert command[0] == sys.executable
    assert command[1].endswith("scripts/install_git_hooks.py")
    assert command[2:4] == ["--repo-root", str(repo_root)]


def test_install_project_runs_from_project_root(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    runner = RecordingRunner()
    install_project(sys.executable, dev=True, runner=runner, project_root=project_root)

    assert runner.commands[0][-2:] == ["-e", ".[dev,interactive]"]
    assert runner.cwds[0] == project_root


def test_resolve_project_root_rejects_invalid_explicit_path(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
    monkeypatch.chdir(project_root)

    invalid = tmp_path / "missing"
    try:
        resolve_project_root(str(invalid))
        assert False, "resolve_project_root should reject invalid explicit path"
    except RuntimeError as exc:
        assert "Invalid --project-root" in str(exc)


def test_resolve_venv_path_relative_to_project_root():
    project_root = Path("/tmp/mdview")
    resolved = resolve_venv_path(".venv-alt", project_root)
    assert resolved == project_root / ".venv-alt"


def test_install_project_production_keeps_interactive_extra(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    runner = RecordingRunner()
    install_project(sys.executable, dev=False, runner=runner, project_root=project_root)

    assert runner.commands[0][-2:] == ["-e", ".[interactive]"]
    assert runner.cwds[0] == project_root
