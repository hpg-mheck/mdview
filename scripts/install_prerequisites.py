"""Install mdview's legacy Python compatibility path and helper utilities.

TheKnowledge's managed starter now treats `install.sh` plus
`scripts/install-stage-2.py` as the canonical POSIX setup path, with
`scripts/install_project.py` holding mdview's project-specific install hook.
This module remains for compatibility with older entry points and current
Windows shims, and it still exposes reusable launcher-management helpers that
the newer hook can import.

Do not treat this file as the primary place to extend mdview's normal POSIX
bootstrap flow. New staged-install behavior belongs in `install.sh`,
`scripts/install-stage-2.py`, or `scripts/install_project.py` unless the
change is specifically about maintaining the legacy compatibility path.
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
        """Record whether commands should execute or only be logged."""

        self.dry_run = dry_run

    def run(self, command: Sequence[str], cwd: Optional[Path] = None) -> None:
        """Run one command, honoring dry-run mode and optional working dir."""

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
    """Load `/etc/os-release` style metadata when available."""

    if not path.exists():
        return {}
    return parse_os_release(path.read_text())


def detect_os_info() -> OSInfo:
    """Detect the host operating system using cross-platform probes."""

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
    """Return the package set mdview expects from one package manager."""

    if manager == "apt-get":
        return ["python3", "python3-venv", "python3-pip", "git"]
    if manager in {"dnf", "yum"}:
        return ["python3", "python3-pip", "python3-virtualenv", "git"]
    if manager == "brew":
        return ["python", "git"]
    return []


def should_use_sudo() -> bool:
    """Return True when package-manager commands should be prefixed with sudo."""

    try:
        if os.geteuid() == 0:
            return False
    except AttributeError:
        return False
    return shutil.which("sudo") is not None


def _with_prefix(prefix: List[str], command: List[str]) -> List[str]:
    """Return a command list with any privilege prefix prepended."""

    return prefix + [part for part in command if part]


def build_install_commands(
    manager: str, packages: List[str], use_sudo: bool, assume_yes: bool = True
) -> List[List[str]]:
    """Build the package-manager commands needed for one bootstrap install."""

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
    """Run package-manager bootstrap commands in the order they were built."""

    for command in commands:
        runner.run(list(command))


MANAGED_MDVIEW_SHIM_MARKER = "# mdview-managed-local-shim"
DEV_SETUP_SCRIPT = Path(__file__).resolve().with_name("dev_setup.py")


def overwrite_unmanaged_mdview_message(path: Path, *, label: str) -> str:
    """Return the refusal text for an unmanaged mdview overwrite target.

    Keep the final line explicit and stable because operator guidance now
    depends on that line staying easy to spot in layered installer output.
    """

    return "\n".join(
        [
            f"Refusing to overwrite unmanaged mdview {label} at {path}.",
            (
                "Use --force if you really want to overwrite your existing "
                f"installed copy at {path.parent}."
            ),
        ]
    )


def _python_module_available(python_executable: str, module_name: str) -> bool:
    """Return True when one Python executable can import the named module."""

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
    """Report which host-level prerequisites are missing before bootstrapping."""

    missing: List[str] = []
    if not _python_module_available(python_executable, "venv"):
        missing.append("venv")
    if not _python_module_available(python_executable, "pip"):
        missing.append("pip")
    if shutil.which("git") is None:
        missing.append("git")
    return missing


def venv_python_path(venv_path: Path) -> Path:
    """Return the Python executable path inside one virtual environment."""

    bin_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return venv_path.joinpath(bin_dir, executable)


def venv_command_path(venv_path: Path, command_name: str) -> Path:
    """Return the path for a command installed inside one virtual environment."""

    bin_dir = "Scripts" if os.name == "nt" else "bin"
    executable = f"{command_name}.exe" if os.name == "nt" else command_name
    return venv_path.joinpath(bin_dir, executable)


def default_mdview_command_path(home: Optional[Path] = None) -> Path:
    """Return the managed user-local shim location for the `mdview` command."""

    base_home = Path.home() if home is None else home
    executable = "mdview.exe" if os.name == "nt" else "mdview"
    return base_home / ".local" / "bin" / executable


def _is_managed_mdview_shim(path: Path) -> bool:
    """Return True when `path` is an mdview shim created by this installer."""

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
    """Return the first PATH `mdview` that is not the checkout-local target."""

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
    """Resolve whether the user wants a managed local `mdview` shim."""

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
    """Return the managed shell shim that delegates to the checkout binary."""

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
    force: bool = False,
    dry_run: bool = False,
    output: Optional[TextIO] = None,
) -> None:
    """Create, remove, or preserve the managed `mdview` command shim."""

    stream = sys.stdout if output is None else output
    shim_path = default_mdview_command_path() if command_path is None else command_path

    if mode == "local":
        if shim_path.exists() and not _is_managed_mdview_shim(shim_path):
            if not force:
                raise RuntimeError(
                    overwrite_unmanaged_mdview_message(
                        shim_path,
                        label="command",
                    )
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
    """Create the project virtual environment when it does not yet exist."""

    python_path = venv_python_path(venv_path)
    if python_path.exists():
        return python_path

    runner.run([python_executable, "-m", "venv", str(venv_path)])
    return python_path


def upgrade_pip_tooling(python_executable: str, runner: CommandRunner) -> None:
    """Refresh packaging helpers inside the selected virtual environment."""

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
    """Return True when `path` looks like the repository root."""

    return (path / "pyproject.toml").exists() or (path / "setup.py").exists()


def resolve_project_root(explicit: Optional[str] = None) -> Path:
    """Resolve the repository root from an explicit path or current context."""

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
    """Resolve the requested virtualenv path relative to the project root."""

    venv_path = Path(venv_value).expanduser()
    if not venv_path.is_absolute():
        venv_path = project_root / venv_path
    return venv_path.resolve()


def install_project(
    python_executable: str, dev: bool, runner: CommandRunner, project_root: Path
) -> None:
    """Install mdview itself in editable mode.

    The project installation always uses the runtime-facing extras only.
    Pinned development tool versions now live in `requirements-dev.txt` and
    are refreshed separately through `scripts/dev_setup.py` so bootstrap and
    steady-state tool policies stay explicit. The `dev` flag remains in the
    signature for call-site compatibility while the installer transition is
    still settling around the newer managed bootstrap model.
    """

    target = ".[interactive]"
    runner.run(
        [python_executable, "-m", "pip", "install", "-e", target], cwd=project_root
    )


def install_git_hooks(
    python_executable: str, runner: CommandRunner, project_root: Path
) -> None:
    """Install the managed git hook wrappers with the selected interpreter."""

    hook_installer = Path(__file__).resolve().with_name("install_git_hooks.py")
    runner.run(
        [python_executable, str(hook_installer), "--repo-root", str(project_root)]
    )


def install_pinned_dev_tools(
    runner: CommandRunner,
    project_root: Path,
    venv_path: Path,
) -> None:
    """Refresh the pinned developer toolchain through `scripts/dev_setup.py`.

    Keep this separate from `install_project()` on purpose. The editable
    project install owns mdview's runtime dependencies, while `dev_setup.py`
    owns the managed Black/Ruff/pytest pin set and runtime-policy selection.
    That separation makes it easier to refresh tooling without changing the
    project install and easier to diagnose whether a failure belongs to the
    repository package or to the managed tool layer.
    """

    runner.run(
        [sys.executable, str(DEV_SETUP_SCRIPT), "--venv", str(venv_path)],
        cwd=project_root,
    )


def validate_platform(os_info: OSInfo) -> None:
    """Reject host platforms outside mdview's documented support set."""

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
    """Parse installer arguments for direct and bootstrap handoff paths."""

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
        "--mdview-command",
        choices=("prompt", "local", "system"),
        default="prompt",
        help=(
            "Select whether typing mdview outside this checkout should use "
            "the local development copy, leave PATH resolution unchanged, or "
            "prompt when interactive."
        ),
    )
    parser.add_argument(
        "--skip-system-packages",
        action="store_true",
        help="Skip apt/dnf/yum/brew bootstrap and only configure Python tooling.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow overwriting an unmanaged existing mdview launcher target.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the mdview prerequisite installer end to end."""

    args = parse_args(argv)
    runner = CommandRunner(dry_run=args.dry_run)

    try:
        project_root = resolve_project_root(args.project_root)
        os_info = detect_os_info()
        validate_platform(os_info)
        print(
            f"Detected platform: {os_info.pretty_name} "
            f"({os_info.platform_id} {os_info.version_id})"
        )

        # Phase 1: host-level prerequisite bootstrap. This remains here for
        # legacy direct-Python entry points and current Windows shims even
        # though the canonical POSIX path now starts at install.sh.
        if args.skip_system_packages:
            print("Skipping system package manager bootstrap (--skip-system-packages).")
        else:
            manager = select_package_manager(os_info)
            if manager is not None:
                missing_tools = collect_missing_system_tools(args.python)
                if missing_tools:
                    packages = system_packages_for(manager)
                    use_sudo = should_use_sudo()
                    commands = build_install_commands(manager, packages, use_sudo)
                    print(
                        "Missing system tools detected: " f"{', '.join(missing_tools)}"
                    )
                    execute_commands(commands, runner)
                else:
                    print(
                        "System prerequisites already available; skipping "
                        "package-manager install."
                    )
            elif os_info.platform_id != "windows":
                raise RuntimeError(
                    "No supported package manager found for this platform."
                )
            else:
                print("Windows detected: skipping system package manager bootstrap.")

        # Phase 2: create the project environment and install mdview itself.
        venv_path = resolve_venv_path(args.venv, project_root)
        venv_python = ensure_virtualenv(args.python, venv_path, runner)
        upgrade_pip_tooling(str(venv_python), runner)
        install_project(
            str(venv_python),
            dev=not args.production,
            runner=runner,
            project_root=project_root,
        )

        # Phase 3: refresh pinned developer tooling only when requested.
        if not args.production:
            install_pinned_dev_tools(runner, project_root, venv_path)

        # Phase 4: install workflow helpers and optional user-local command
        # shims after the environment contents are in place.
        install_git_hooks(str(venv_python), runner=runner, project_root=project_root)
        local_mdview = venv_command_path(venv_path, "mdview")
        alternate_mdview = detect_noncheckout_mdview(local_mdview)
        command_mode = resolve_mdview_command_mode(
            args.mdview_command,
            interactive=sys.stdin.isatty() and sys.stdout.isatty(),
            alternate_mdview=alternate_mdview,
        )
        apply_mdview_command_mode(
            command_mode,
            local_mdview,
            force=args.force,
            dry_run=args.dry_run,
        )
    except (RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        print(f"[install-prerequisites] FAIL: {error}", file=sys.stderr)
        return 1

    print(f"Environment ready in {venv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
