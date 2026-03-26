import io
import os
import sys
from pathlib import Path

from scripts.install_prerequisites import (
    MANAGED_MDVIEW_SHIM_MARKER,
    CommandRunner,
    OSInfo,
    apply_mdview_command_mode,
    build_install_commands,
    collect_missing_system_tools,
    detect_noncheckout_mdview,
    default_mdview_command_path,
    ensure_virtualenv,
    install_project,
    install_git_hooks,
    parse_os_release,
    resolve_mdview_command_mode,
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
    assert "git" in packages
    assert "less" not in packages


def test_ensure_virtualenv_requests_creation_when_missing(tmp_path: Path):
    venv_path = tmp_path / "venv"
    runner = RecordingRunner()
    created_python = ensure_virtualenv(sys.executable, venv_path, runner)
    expected_python = venv_path / "bin" / "python"
    assert created_python == expected_python
    assert runner.commands[0][:3] == [sys.executable, "-m", "venv"]


def test_collect_missing_system_tools_returns_empty_when_ready(monkeypatch):
    monkeypatch.setattr(
        "scripts.install_prerequisites._python_module_available",
        lambda python_executable, module_name: True,
    )
    monkeypatch.setattr(
        "scripts.install_prerequisites.shutil.which",
        lambda command: f"/usr/bin/{command}",
    )

    assert collect_missing_system_tools(sys.executable) == []


def test_collect_missing_system_tools_reports_missing_items(monkeypatch):
    def fake_python_module_available(python_executable, module_name):
        return module_name == "venv"

    def fake_which(command):
        return None if command == "git" else f"/usr/bin/{command}"

    monkeypatch.setattr(
        "scripts.install_prerequisites._python_module_available",
        fake_python_module_available,
    )
    monkeypatch.setattr("scripts.install_prerequisites.shutil.which", fake_which)

    assert collect_missing_system_tools(sys.executable) == ["pip", "git"]


def test_detect_noncheckout_mdview_skips_local_target_and_managed_shim(tmp_path):
    local_dir = tmp_path / "repo" / ".venv" / "bin"
    local_dir.mkdir(parents=True)
    local_mdview = local_dir / "mdview"
    local_mdview.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    local_mdview.chmod(0o755)

    home = tmp_path / "home"
    shim_path = default_mdview_command_path(home=home)
    shim_path.parent.mkdir(parents=True)
    shim_path.write_text(
        "#!/usr/bin/env bash\n"
        f"{MANAGED_MDVIEW_SHIM_MARKER}\n"
        'exec "/tmp/repo/.venv/bin/mdview" "$@"\n',
        encoding="utf-8",
    )
    shim_path.chmod(0o755)

    system_dir = tmp_path / "usr" / "bin"
    system_dir.mkdir(parents=True)
    system_mdview = system_dir / "mdview"
    system_mdview.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    system_mdview.chmod(0o755)

    detected = detect_noncheckout_mdview(
        local_mdview,
        path_env=os.pathsep.join(
            [str(local_dir), str(shim_path.parent), str(system_dir)]
        ),
        command_path=shim_path,
    )

    assert detected == system_mdview


def test_resolve_mdview_command_mode_reports_detected_alternate():
    output = io.StringIO()

    mode = resolve_mdview_command_mode(
        "prompt",
        interactive=True,
        alternate_mdview=Path("/usr/bin/mdview"),
        input_func=lambda prompt: "y",
        output=output,
    )

    assert mode == "local"
    assert "Another mdview command appears on PATH" in output.getvalue()


def test_resolve_mdview_command_mode_reports_absence_before_prompt():
    output = io.StringIO()
    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return "n"

    mode = resolve_mdview_command_mode(
        "prompt",
        interactive=True,
        alternate_mdview=None,
        input_func=fake_input,
        output=output,
    )

    assert mode == "system"
    assert "No other mdview command detected on PATH" in output.getvalue()
    assert prompts == [
        "When you type 'mdview' outside this checkout, install a managed "
        "local shim so the development copy wins? [y/N]: "
    ]


def test_resolve_mdview_command_mode_defaults_to_system_when_noninteractive():
    output = io.StringIO()

    mode = resolve_mdview_command_mode(
        "prompt",
        interactive=False,
        alternate_mdview=None,
        output=output,
    )

    assert mode == "system"
    text = output.getvalue()
    assert "No other mdview command detected on PATH" in text
    assert "Non-interactive install" in text


def test_apply_mdview_command_mode_local_writes_managed_shim(tmp_path):
    local_mdview = tmp_path / "repo" / ".venv" / "bin" / "mdview"
    local_mdview.parent.mkdir(parents=True)
    local_mdview.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    local_mdview.chmod(0o755)
    shim_path = tmp_path / "home" / ".local" / "bin" / "mdview"
    output = io.StringIO()

    apply_mdview_command_mode(
        "local", local_mdview, command_path=shim_path, output=output
    )

    contents = shim_path.read_text(encoding="utf-8")
    assert MANAGED_MDVIEW_SHIM_MARKER in contents
    assert str(local_mdview) in contents
    assert "Installed managed mdview shim" in output.getvalue()


def test_apply_mdview_command_mode_system_removes_managed_shim(tmp_path):
    local_mdview = tmp_path / "repo" / ".venv" / "bin" / "mdview"
    local_mdview.parent.mkdir(parents=True)
    local_mdview.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    shim_path = tmp_path / "home" / ".local" / "bin" / "mdview"
    shim_path.parent.mkdir(parents=True)
    shim_path.write_text(
        "#!/usr/bin/env bash\n"
        f"{MANAGED_MDVIEW_SHIM_MARKER}\n"
        'exec "/tmp/repo/.venv/bin/mdview" "$@"\n',
        encoding="utf-8",
    )
    output = io.StringIO()

    apply_mdview_command_mode(
        "system", local_mdview, command_path=shim_path, output=output
    )

    assert not shim_path.exists()
    assert "Removed managed mdview shim" in output.getvalue()


def test_apply_mdview_command_mode_local_rejects_unmanaged_shim(tmp_path):
    local_mdview = tmp_path / "repo" / ".venv" / "bin" / "mdview"
    local_mdview.parent.mkdir(parents=True)
    local_mdview.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    local_mdview.chmod(0o755)
    shim_path = tmp_path / "home" / ".local" / "bin" / "mdview"
    shim_path.parent.mkdir(parents=True)
    shim_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    try:
        apply_mdview_command_mode("local", local_mdview, command_path=shim_path)
    except RuntimeError as error:
        assert "Refusing to overwrite unmanaged mdview command" in str(error)
    else:
        raise AssertionError("Expected unmanaged shim overwrite to fail.")


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
