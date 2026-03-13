"""
Installer for mdview prerequisites across supported environments.

This script installs system dependencies, provisions a virtual environment, and
installs the project with development extras. It supports Rocky Linux 9.6,
Fedora 43, Ubuntu 24.x, Linux Mint, Debian, and modern macOS versions.
"""

from __future__ import annotations

import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, TextIO


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

    def run(self, command: Sequence[str]) -> None:
        printable = " ".join(command)
        print(f"-> {printable}")
        if self.dry_run:
            return
        subprocess.run(command, check=True)


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


MANAGED_MDVIEW_SHIM_MARKER = "# mdview-managed-local-shim"


def _python_module_available(python_executable: str, module_name: str) -> bool:
    try:
        result = subprocess.run(
            [python_executable, "-c", f"import {module_name}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return result.returncode == 0


def collect_missing_system_tools(python_executable: str) -> List[str]:
    missing: List[str] = []
    if not _python_module_available(python_executable, "venv"):
        missing.append("venv")
    if not _python_module_available(python_executable, "pip"):
        missing.append("pip")
    if shutil.which("less") is None:
        missing.append("less")
    if shutil.which("git") is None:
        missing.append("git")
    return missing


def venv_python_path(venv_path: Path) -> Path:
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return venv_path.joinpath(bin_dir, executable)


def venv_command_path(venv_path: Path, command_name: str) -> Path:
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    executable = f"{command_name}.exe" if os.name == "nt" else command_name
    return venv_path.joinpath(bin_dir, executable)


def default_mdview_command_path(home: Optional[Path] = None) -> Path:
    base_home = Path.home() if home is None else home
    executable = "mdview.exe" if os.name == "nt" else "mdview"
    return base_home / ".local" / "bin" / executable


def _is_managed_mdview_shim(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        return MANAGED_MDVIEW_SHIM_MARKER in path.read_text(encoding="utf-8")
    except OSError:
        return False


def detect_noncheckout_mdview(
    local_mdview: Path,
    *,
    path_env: Optional[str] = None,
    command_path: Optional[Path] = None,
) -> Optional[Path]:
    search_path = os.environ.get("PATH", "") if path_env is None else path_env
    managed_command = (
        default_mdview_command_path() if command_path is None else command_path
    )
    local_resolved = local_mdview.resolve(strict=False)
    executable = managed_command.name

    for raw_entry in search_path.split(os.pathsep):
        if not raw_entry:
            continue
        candidate = Path(raw_entry) / executable
        if not candidate.exists() or not os.access(candidate, os.X_OK):
            continue
        if candidate == managed_command and _is_managed_mdview_shim(candidate):
            continue
        if candidate.resolve(strict=False) == local_resolved:
            continue
        return candidate

    return None


def resolve_mdview_command_mode(
    requested_mode: str,
    *,
    interactive: bool,
    alternate_mdview: Optional[Path],
    input_func: Callable[[str], str] = input,
    output: Optional[TextIO] = None,
) -> str:
    stream = sys.stdout if output is None else output

    if alternate_mdview is None:
        print(
            "No other mdview command detected on PATH outside this checkout.",
            file=stream,
        )
    else:
        print(
            f"Another mdview command appears on PATH at {alternate_mdview}.",
            file=stream,
        )

    if requested_mode in {"local", "system"}:
        return requested_mode

    if not interactive:
        print(
            "Non-interactive install: leaving mdview PATH resolution unchanged. "
            "Use --mdview-command local or --mdview-command system to override.",
            file=stream,
        )
        return "system"

    prompt = (
        "When you type 'mdview' outside this checkout, use the local "
        "development copy instead of the other PATH result? [y/N]: "
    )
    if alternate_mdview is None:
        prompt = (
            "When you type 'mdview' outside this checkout, install a managed "
            "local shim so the development copy wins? [y/N]: "
        )

    response = input_func(prompt).strip()
    return "local" if response.lower() in {"y", "yes"} else "system"


def _managed_mdview_shim_contents(local_mdview: Path) -> str:
    quoted_target = shlex.quote(str(local_mdview))
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            MANAGED_MDVIEW_SHIM_MARKER,
            f"TARGET={quoted_target}",
            'if [ ! -x "$TARGET" ]; then',
            '  echo "mdview shim target missing: $TARGET" >&2',
            "  exit 1",
            "fi",
            'exec "$TARGET" "$@"',
            "",
        ]
    )


def apply_mdview_command_mode(
    mode: str,
    local_mdview: Path,
    *,
    command_path: Optional[Path] = None,
    dry_run: bool = False,
    output: Optional[TextIO] = None,
) -> None:
    stream = sys.stdout if output is None else output
    shim_path = default_mdview_command_path() if command_path is None else command_path

    if mode == "local":
        if shim_path.exists() and not _is_managed_mdview_shim(shim_path):
            raise RuntimeError(
                f"Refusing to overwrite unmanaged mdview command at {shim_path}."
            )
        if not dry_run and not local_mdview.exists():
            raise RuntimeError(
                f"Local development mdview entry point does not exist: {local_mdview}"
            )
        if dry_run:
            print(
                f"Would install managed mdview shim at {shim_path} -> {local_mdview}",
                file=stream,
            )
            return

        shim_path.parent.mkdir(parents=True, exist_ok=True)
        shim_path.write_text(
            _managed_mdview_shim_contents(local_mdview), encoding="utf-8"
        )
        shim_path.chmod(0o755)
        print(
            f"Installed managed mdview shim at {shim_path} -> {local_mdview}",
            file=stream,
        )
        return

    if mode != "system":
        raise ValueError(f"Unsupported mdview command mode: {mode}")

    if not shim_path.exists():
        print("Leaving mdview PATH resolution unchanged.", file=stream)
        return

    if not _is_managed_mdview_shim(shim_path):
        print(
            f"Leaving existing unmanaged mdview command untouched at {shim_path}.",
            file=stream,
        )
        return

    if dry_run:
        print(f"Would remove managed mdview shim at {shim_path}", file=stream)
        return

    shim_path.unlink()
    print(f"Removed managed mdview shim at {shim_path}", file=stream)


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


def install_project(python_executable: str, dev: bool, runner: CommandRunner) -> None:
    target = ".[dev]" if dev else "."
    runner.run([python_executable, "-m", "pip", "install", "-e", target])


def validate_platform(os_info: OSInfo) -> None:
    supported = {
        "ubuntu",
        "debian",
        "linuxmint",
        "mint",
        "rocky",
        "fedora",
        "macos",
    }
    if os_info.platform_id not in supported:
        raise RuntimeError(
            "Unsupported platform: {platform}. Supported platforms include "
            "Rocky Linux 9.6, Fedora 43, Ubuntu 24.x, Linux Mint, Debian, and "
            "modern macOS releases.".format(platform=os_info.pretty_name)
        )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install mdview prerequisites.")
    parser.add_argument(
        "--venv",
        default=str(Path(__file__).resolve().parent.parent / ".venv"),
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
        "--mdview-command",
        choices=("prompt", "local", "system"),
        default="prompt",
        help=(
            "Select whether typing mdview outside this checkout should use "
            "the local development copy, leave PATH resolution unchanged, or "
            "prompt when interactive."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    runner = CommandRunner(dry_run=args.dry_run)

    os_info = detect_os_info()
    validate_platform(os_info)

    manager = select_package_manager(os_info)
    if manager is None:
        raise RuntimeError("No supported package manager found for this platform.")

    print(
        f"Detected platform: {os_info.pretty_name} ({os_info.platform_id} {os_info.version_id})"
    )
    missing_tools = collect_missing_system_tools(args.python)
    if missing_tools:
        packages = system_packages_for(manager)
        use_sudo = should_use_sudo()
        commands = build_install_commands(manager, packages, use_sudo)
        print(f"Missing system tools detected: {', '.join(missing_tools)}")
        execute_commands(commands, runner)
    else:
        print(
            "System prerequisites already available; skipping package-manager install."
        )

    venv_path = Path(args.venv).resolve()
    venv_python = ensure_virtualenv(args.python, venv_path, runner)
    upgrade_pip_tooling(str(venv_python), runner)
    install_project(str(venv_python), dev=not args.production, runner=runner)
    local_mdview = venv_command_path(venv_path, "mdview")
    alternate_mdview = detect_noncheckout_mdview(local_mdview)
    command_mode = resolve_mdview_command_mode(
        args.mdview_command,
        interactive=sys.stdin.isatty() and sys.stdout.isatty(),
        alternate_mdview=alternate_mdview,
    )
    apply_mdview_command_mode(command_mode, local_mdview, dry_run=args.dry_run)
    print(f"Environment ready in {venv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
