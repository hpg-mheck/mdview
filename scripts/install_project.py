#!/usr/bin/env python3
"""Apply mdview-specific install behavior under the managed stage-two flow.

TheKnowledge's managed `scripts/install-stage-2.py` now owns the shared
bootstrap, pyenv, virtualenv, and shell-hook workflow. This repository keeps
its project-specific semantics here:
- how mdview itself is installed into the selected virtual environment; and
- how the user-facing `mdview` launcher behaves for development versus
  standard installs.

Keep this hook focused on mdview policy. Shared bootstrap/runtime behavior
belongs in the managed starter files, not here.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from install_prerequisites import (  # noqa: E402
    overwrite_unmanaged_mdview_message,
    resolve_mdview_command_mode,
)

DEV_LAUNCHER_MARKER = "# mdview-managed-dev-launcher"
STANDARD_LAUNCHER_MARKER = "# mdview-managed-standard-launcher"
STANDARD_LAUNCHER_BACKUP_NAME = ".mdview-standard-launcher.backup"
DEV_LAUNCHER_MODE_ENV = "MDVIEW_DEV_LAUNCHER_MODE"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the managed install-hook arguments from stage two."""

    parser = argparse.ArgumentParser(
        description=(
            "Run mdview's project-specific install hook for one managed "
            "install mode and scope."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("standard", "dev", "venv-only"),
        required=True,
        help="Install mode selected by scripts/install-stage-2.py.",
    )
    parser.add_argument(
        "--scope",
        choices=("repo", "user", "system"),
        required=True,
        help="Install scope selected by scripts/install-stage-2.py.",
    )
    parser.add_argument(
        "--python",
        required=True,
        help="Python executable inside the managed install virtualenv.",
    )
    parser.add_argument(
        "--venv",
        type=Path,
        required=True,
        help="Managed virtualenv path for this install mode.",
    )
    parser.add_argument(
        "--bin-dir",
        type=Path,
        required=True,
        help="Directory where the managed launcher should live for this scope.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow overwriting an unmanaged existing mdview launcher target.",
    )
    return parser.parse_args(argv)


def run(command: Sequence[str | Path], *, cwd: Path = REPO_ROOT) -> None:
    """Run one subprocess from the repository root with logging."""

    printable = " ".join(str(part) for part in command)
    print(f"[install-project] -> {printable}")
    subprocess.run([str(part) for part in command], cwd=cwd, check=True)


def venv_command_path(venv_path: Path, command_name: str) -> Path:
    """Return the install-scope command path inside one virtualenv."""

    bin_dir = "Scripts" if os.name == "nt" else "bin"
    executable = f"{command_name}.exe" if os.name == "nt" else command_name
    return venv_path / bin_dir / executable


def mdview_launcher_path(bin_dir: Path) -> Path:
    """Return the launcher path for the user-facing `mdview` command."""

    executable = "mdview.exe" if os.name == "nt" else "mdview"
    return bin_dir / executable


def launcher_backup_path(bin_dir: Path) -> Path:
    """Return the sidecar file used to restore a standard launcher after dev."""

    return bin_dir / STANDARD_LAUNCHER_BACKUP_NAME


def read_text_if_file(path: Path) -> str:
    """Return file contents, or an empty string when the file is absent."""

    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def is_managed_dev_launcher(path: Path) -> bool:
    """Return True when the path is one of mdview's managed dev launchers."""

    return DEV_LAUNCHER_MARKER in read_text_if_file(path)


def is_managed_standard_launcher(path: Path) -> bool:
    """Return True when the path is one of mdview's managed standard launchers."""

    return STANDARD_LAUNCHER_MARKER in read_text_if_file(path)


def is_managed_launcher(path: Path) -> bool:
    """Return True when mdview created the launcher and may replace it safely."""

    return is_managed_dev_launcher(path) or is_managed_standard_launcher(path)


def standard_launcher_contents(target: Path) -> str:
    """Build the stable launcher that delegates to a standard-install venv."""

    quoted_target = shlex.quote(str(target))
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            STANDARD_LAUNCHER_MARKER,
            f"TARGET={quoted_target}",
            'if [ ! -x "$TARGET" ]; then',
            '  echo "mdview launcher target missing: $TARGET" >&2',
            "  exit 1",
            "fi",
            'exec "$TARGET" "$@"',
            "",
        ]
    )


def dev_launcher_contents(target: Path) -> str:
    """Build the project-bound dev launcher that delegates to repo `.venv`."""

    quoted_target = shlex.quote(str(target))
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            DEV_LAUNCHER_MARKER,
            f"TARGET={quoted_target}",
            'if [ ! -x "$TARGET" ]; then',
            '  echo "mdview development launcher target missing: $TARGET" >&2',
            "  exit 1",
            "fi",
            'exec "$TARGET" "$@"',
            "",
        ]
    )


def write_executable(path: Path, contents: str) -> None:
    """Write one launcher file and mark it executable."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def install_package(python_executable: str, *, editable: bool) -> None:
    """Install mdview into the selected managed virtual environment."""

    command: list[str] = [
        python_executable,
        "-m",
        "pip",
        "install",
        "--no-build-isolation",
    ]
    if editable:
        command.extend(["--editable", ".[interactive]"])
    else:
        command.append(".[interactive]")
    run(command)


def detect_other_mdview_on_path(
    local_mdview: Path, launcher_path: Path
) -> Optional[Path]:
    """Return the first PATH `mdview` candidate that is not the local target."""

    local_resolved = local_mdview.resolve(strict=False)
    for raw_entry in os.environ.get("PATH", "").split(os.pathsep):
        if not raw_entry:
            continue
        candidate = Path(raw_entry) / launcher_path.name
        if not candidate.exists() or not os.access(candidate, os.X_OK):
            continue
        if candidate.resolve(strict=False) == local_resolved:
            continue
        return candidate
    return None


def requested_dev_launcher_mode() -> str:
    """Return the requested dev-launcher mode from environment policy."""

    requested = os.environ.get(DEV_LAUNCHER_MODE_ENV, "prompt").strip().lower()
    if requested in {"prompt", "local", "system"}:
        return requested
    raise RuntimeError(
        f"{DEV_LAUNCHER_MODE_ENV} must be one of prompt, local, or system."
    )


def install_standard_launcher(
    launcher_path: Path, target: Path, backup_path: Path, *, force: bool
) -> None:
    """Install or refresh the stable user/system launcher for mdview."""

    if launcher_path.exists() and not is_managed_launcher(launcher_path):
        if not force:
            raise RuntimeError(
                overwrite_unmanaged_mdview_message(
                    launcher_path,
                    label="launcher",
                )
            )
    write_executable(launcher_path, standard_launcher_contents(target))
    if backup_path.exists():
        backup_path.unlink()
    print(f"[install-project] Installed standard launcher at {launcher_path}")


def install_dev_launcher(
    launcher_path: Path,
    target: Path,
    backup_path: Path,
    *,
    force: bool,
) -> None:
    """Install the project-bound dev launcher, preserving any standard one."""

    if launcher_path.exists() and not is_managed_launcher(launcher_path):
        if not force:
            raise RuntimeError(
                overwrite_unmanaged_mdview_message(
                    launcher_path,
                    label="launcher",
                )
            )
    if launcher_path.exists() and is_managed_standard_launcher(launcher_path):
        backup_path.write_text(read_text_if_file(launcher_path), encoding="utf-8")
    write_executable(launcher_path, dev_launcher_contents(target))
    print(f"[install-project] Installed development launcher at {launcher_path}")


def restore_nondev_launcher(launcher_path: Path, backup_path: Path) -> None:
    """Restore the prior standard launcher or remove the dev launcher."""

    if backup_path.exists():
        write_executable(launcher_path, backup_path.read_text(encoding="utf-8"))
        backup_path.unlink()
        print(f"[install-project] Restored standard launcher at {launcher_path}")
        return
    if launcher_path.exists() and is_managed_dev_launcher(launcher_path):
        launcher_path.unlink()
        print(f"[install-project] Removed development launcher at {launcher_path}")
        return
    if launcher_path.exists():
        print(f"[install-project] Leaving launcher unchanged at {launcher_path}")
        return
    print("[install-project] Leaving launcher resolution unchanged.")


def handle_standard_install(
    python_executable: str, venv_path: Path, bin_dir: Path, *, force: bool
) -> None:
    """Install mdview for standard mode and publish its stable launcher."""

    install_package(python_executable, editable=False)
    launcher_path = mdview_launcher_path(bin_dir)
    backup_path = launcher_backup_path(bin_dir)
    target = venv_command_path(venv_path, "mdview")
    install_standard_launcher(launcher_path, target, backup_path, force=force)


def handle_dev_install(
    python_executable: str,
    venv_path: Path,
    bin_dir: Path,
    *,
    force: bool,
) -> None:
    """Install mdview for development mode and manage the optional dev launcher."""

    install_package(python_executable, editable=True)
    launcher_path = mdview_launcher_path(bin_dir)
    backup_path = launcher_backup_path(bin_dir)
    local_mdview = venv_command_path(venv_path, "mdview")
    alternate_mdview = detect_other_mdview_on_path(local_mdview, launcher_path)
    command_mode = resolve_mdview_command_mode(
        requested_dev_launcher_mode(),
        interactive=sys.stdin.isatty() and sys.stdout.isatty(),
        alternate_mdview=alternate_mdview,
    )
    if command_mode == "local":
        install_dev_launcher(
            launcher_path,
            local_mdview,
            backup_path,
            force=force,
        )
        return
    restore_nondev_launcher(launcher_path, backup_path)


def main(argv: Sequence[str] | None = None) -> int:
    """Run mdview's install hook for the selected managed mode."""

    args = parse_args(argv or sys.argv[1:])
    try:
        if args.mode == "venv-only":
            print("[install-project] venv-only mode: no project install requested.")
            return 0
        if args.mode == "dev":
            handle_dev_install(
                args.python,
                args.venv,
                args.bin_dir,
                force=args.force,
            )
            return 0
        handle_standard_install(
            args.python,
            args.venv,
            args.bin_dir,
            force=args.force,
        )
        return 0
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"[install-project] FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
