import sys
from pathlib import Path

from scripts.install_prerequisites import (
    CommandRunner,
    OSInfo,
    build_install_commands,
    ensure_virtualenv,
    parse_os_release,
    select_package_manager,
    system_packages_for,
)


class RecordingRunner(CommandRunner):
    def __init__(self, dry_run: bool = True):
        super().__init__(dry_run=dry_run)
        self.commands = []

    def run(self, command):
        self.commands.append(list(command))
        super().run(command)


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
