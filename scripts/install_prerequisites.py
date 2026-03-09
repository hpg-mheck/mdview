"""
Installer for mdview prerequisites across supported environments.

This script installs system dependencies, provisions a virtual environment, and
installs the project with development extras. It supports Rocky Linux 9.6,
Fedora 43, Ubuntu 24.x, Linux Mint, Debian, modern macOS versions, and
Windows 11 command-line environments.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence


@dataclass
class OSInfo:
    """Information parsed from the host operating system."""

    platform_id: str
    version_id: str
    pretty_name: str


class CommandRunner:
    """Execute shell commands with optional dry-run support."""

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def run(self, command: Sequence[str], cwd: Optional[Path] = None) -> None:
        printable = " ".join(command)
        if cwd is None:
            print(f"-> {printable}")
        else:
            print(f"-> (cd {cwd} && {printable})")
        if self.dry_run:
            return
        subprocess.run(command, check=True, cwd=str(cwd) if cwd else None)


def parse_os_release(content: str) -> Dict[str, str]:
    """Parse the contents of an os-release style string."""

    data: Dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key] = value.strip().strip('"')
    return data


def load_os_release(path: Path = Path("/etc/os-release")) -> Dict[str, str]:
    if not path.exists():
        return {}
    return parse_os_release(path.read_text())


def detect_os_info() -> OSInfo:
    system = platform.system().lower()
    if system == "windows":
        version = platform.version()
        return OSInfo("windows", version, "Windows")
    if system == "darwin":
        version = platform.mac_ver()[0]
        return OSInfo("macos", version, "macOS")

    if system == "linux":
        release = load_os_release()
        platform_id = release.get("ID", "linux").lower()
        version_id = release.get("VERSION_ID", "")
        pretty_name = release.get("PRETTY_NAME", platform_id)
        return OSInfo(platform_id, version_id, pretty_name)

    return OSInfo(system, "", system)


def select_package_manager(
    os_info: OSInfo, available: Optional[Iterable[str]] = None
) -> Optional[str]:
    """Choose the best-fit package manager for the detected platform."""

    if os_info.platform_id == "windows":
        return None

    preferred: List[str] = []
    if os_info.platform_id in {"ubuntu", "debian", "linuxmint", "mint"}:
        preferred.append("apt-get")
    elif os_info.platform_id in {"rocky", "fedora"}:
        preferred.extend(["dnf", "yum"])
    elif os_info.platform_id == "macos":
        preferred.append("brew")

    search_order = preferred + ["apt-get", "dnf", "yum", "brew"]
    if available is None:
        available = [cmd for cmd in search_order if shutil.which(cmd)]
    available_set = set(available)
    for candidate in search_order:
        if candidate in available_set:
            return candidate
    return None


def system_packages_for(manager: str) -> List[str]:
    if manager == "apt-get":
        return ["python3", "python3-venv", "python3-pip", "less", "git"]
    if manager in {"dnf", "yum"}:
        return ["python3", "python3-pip", "python3-virtualenv", "less", "git"]
    if manager == "brew":
        return ["python", "git", "less"]
    return []


def should_use_sudo() -> bool:
    try:
        if os.geteuid() == 0:
            return False
    except AttributeError:
        return False
    return shutil.which("sudo") is not None


def _with_prefix(prefix: List[str], command: List[str]) -> List[str]:
    return prefix + [part for part in command if part]


def build_install_commands(
    manager: str, packages: List[str], use_sudo: bool, assume_yes: bool = True
) -> List[List[str]]:
    prefix: List[str] = ["sudo"] if use_sudo else []
    commands: List[List[str]] = []

    if manager == "apt-get":
        commands.append(_with_prefix(prefix, [manager, "update"]))
        install_cmd = [manager]
        if assume_yes:
            install_cmd.append("-y")
        install_cmd.append("install")
        install_cmd.extend(packages)
        commands.append(_with_prefix(prefix, install_cmd))
    elif manager in {"dnf", "yum"}:
        install_cmd = [manager]
        if assume_yes:
            install_cmd.append("-y")
        install_cmd.append("install")
        install_cmd.extend(packages)
        commands.append(_with_prefix(prefix, install_cmd))
    elif manager == "brew":
        commands.append([manager, "update"])
        commands.append([manager, "install"] + packages)
    else:
        raise ValueError(f"Unsupported package manager: {manager}")

    return commands


def execute_commands(commands: Iterable[Sequence[str]], runner: CommandRunner) -> None:
    for command in commands:
        runner.run(list(command))


def venv_python_path(venv_path: Path) -> Path:
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return venv_path.joinpath(bin_dir, executable)


def ensure_virtualenv(
    python_executable: str, venv_path: Path, runner: CommandRunner
) -> Path:
    python_path = venv_python_path(venv_path)
    if python_path.exists():
        return python_path

    runner.run([python_executable, "-m", "venv", str(venv_path)])
    return python_path


def upgrade_pip_tooling(python_executable: str, runner: CommandRunner) -> None:
    runner.run(
        [
            python_executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ]
    )


def is_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() or (path / "setup.py").exists()


def resolve_project_root(explicit: Optional[str] = None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if is_project_root(candidate):
            return candidate
        raise RuntimeError(
            f"Invalid --project-root: {candidate}. Expected pyproject.toml "
            "or setup.py in that directory."
        )

    candidate = Path(__file__).resolve().parent.parent
    if is_project_root(candidate):
        return candidate

    for parent in [Path.cwd().resolve(), *Path.cwd().resolve().parents]:
        if is_project_root(parent):
            return parent

    raise RuntimeError(
        "Unable to resolve project root. Pass --project-root to a directory "
        "containing pyproject.toml or setup.py."
    )


def resolve_venv_path(venv_value: str, project_root: Path) -> Path:
    venv_path = Path(venv_value).expanduser()
    if not venv_path.is_absolute():
        venv_path = project_root / venv_path
    return venv_path.resolve()


def install_project(
    python_executable: str, dev: bool, runner: CommandRunner, project_root: Path
) -> None:
    target = ".[dev,interactive]" if dev else ".[interactive]"
    runner.run(
        [python_executable, "-m", "pip", "install", "-e", target], cwd=project_root
    )


def install_git_hooks(
    python_executable: str, runner: CommandRunner, project_root: Path
) -> None:
    hook_installer = Path(__file__).resolve().with_name("install_git_hooks.py")
    runner.run(
        [python_executable, str(hook_installer), "--repo-root", str(project_root)]
    )


def validate_platform(os_info: OSInfo) -> None:
    supported = {
        "ubuntu",
        "debian",
        "linuxmint",
        "mint",
        "rocky",
        "fedora",
        "macos",
        "windows",
    }
    if os_info.platform_id not in supported:
        raise RuntimeError(
            "Unsupported platform: {platform}. Supported platforms include "
            "Rocky Linux 9.6, Fedora 43, Ubuntu 24.x, Linux Mint, Debian, and "
            "modern macOS releases, plus Windows 11 command-line shells.".format(
                platform=os_info.pretty_name
            )
        )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install mdview prerequisites.")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parent.parent),
        help="Repository root containing pyproject.toml or setup.py.",
    )
    parser.add_argument(
        "--venv",
        default=".venv",
        help="Virtual environment path.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to create virtualenvs.",
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Install only runtime dependencies (skip dev extras).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print commands without executing them."
    )
    parser.add_argument(
        "--skip-system-packages",
        action="store_true",
        help="Skip apt/dnf/yum/brew bootstrap and only configure Python tooling.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    runner = CommandRunner(dry_run=args.dry_run)
    project_root = resolve_project_root(args.project_root)

    os_info = detect_os_info()
    validate_platform(os_info)

    print(
        f"Detected platform: {os_info.pretty_name} ({os_info.platform_id} {os_info.version_id})"
    )

    if args.skip_system_packages:
        print("Skipping system package manager bootstrap (--skip-system-packages).")
    else:
        manager = select_package_manager(os_info)
        if manager is not None:
            packages = system_packages_for(manager)
            use_sudo = should_use_sudo()
            commands = build_install_commands(manager, packages, use_sudo)
            execute_commands(commands, runner)
        elif os_info.platform_id != "windows":
            raise RuntimeError("No supported package manager found for this platform.")
        else:
            print("Windows detected: skipping system package manager bootstrap.")

    venv_path = resolve_venv_path(args.venv, project_root)
    venv_python = ensure_virtualenv(args.python, venv_path, runner)
    upgrade_pip_tooling(str(venv_python), runner)
    install_project(
        str(venv_python),
        dev=not args.production,
        runner=runner,
        project_root=project_root,
    )
    install_git_hooks(str(venv_python), runner=runner, project_root=project_root)
    print(f"Environment ready in {venv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
