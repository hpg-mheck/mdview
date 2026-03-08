#!/usr/bin/env python3
"""Install managed git hook wrappers for local developer workflows."""

from __future__ import annotations

import argparse
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class HookSpec:
    name: str
    marker_label: str


HOOK_SPECS = (
    HookSpec(name="pre-commit", marker_label="mdview entropy pre-commit"),
    HookSpec(name="pre-push", marker_label="mdview quality gate pre-push"),
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install managed pre-commit and pre-push hook wrappers for mdview."
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parent.parent),
        help="Repository root containing the .git directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended actions without writing files.",
    )
    return parser.parse_args(argv)


def ensure_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def start_marker(spec: HookSpec) -> str:
    return f"# >>> {spec.marker_label} >>>"


def end_marker(spec: HookSpec) -> str:
    return f"# <<< {spec.marker_label} <<<"


def managed_block(spec: HookSpec) -> str:
    if spec.name == "pre-commit":
        command_lines = [
            "if command -v python >/dev/null 2>&1; then",
            "  python scripts/run_tool_with_timeout.py entropy_check",
            "elif command -v python3 >/dev/null 2>&1; then",
            "  python3 scripts/run_tool_with_timeout.py entropy_check",
            "else",
            '  echo "[mdview pre-commit] python/python3 not found." >&2',
            "  exit 1",
            "fi",
        ]
    elif spec.name == "pre-push":
        command_lines = [
            "if command -v python >/dev/null 2>&1; then",
            '  if [ "${MDVIEW_QUALITY_GATE_NO_CACHE:-0}" = "1" ]; then',
            "    python scripts/run_quality_gate_cached.py --no-cache",
            "  else",
            "    python scripts/run_quality_gate_cached.py",
            "  fi",
            "elif command -v python3 >/dev/null 2>&1; then",
            '  if [ "${MDVIEW_QUALITY_GATE_NO_CACHE:-0}" = "1" ]; then',
            "    python3 scripts/run_quality_gate_cached.py --no-cache",
            "  else",
            "    python3 scripts/run_quality_gate_cached.py",
            "  fi",
            "else",
            '  echo "[mdview pre-push] python/python3 not found." >&2',
            "  exit 1",
            "fi",
        ]
    else:  # pragma: no cover - defensive guardrail for future extension.
        raise RuntimeError(f"Unsupported hook name: {spec.name}")

    lines = [start_marker(spec), *command_lines, end_marker(spec)]
    return "\n".join(lines)


def is_managed_hook(existing_text: str, spec: HookSpec) -> bool:
    return start_marker(spec) in existing_text and end_marker(spec) in existing_text


def render_wrapper(spec: HookSpec) -> str:
    local_hook = f".git/hooks/{spec.name}.local"
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f'if [ -x "{local_hook}" ]; then',
        f'  "{local_hook}" "$@"',
        "fi",
        "",
        managed_block(spec),
        "",
    ]
    return "\n".join(lines)


def install_hook(repo_root: Path, spec: HookSpec, dry_run: bool = False) -> Path:
    hooks_dir = repo_root / ".git" / "hooks"
    if not hooks_dir.exists():
        raise RuntimeError(f"Missing hooks directory: {hooks_dir}")

    hook_path = hooks_dir / spec.name
    local_hook_path = hooks_dir / f"{spec.name}.local"

    existing = ""
    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8", errors="replace")

    managed = is_managed_hook(existing, spec)
    if hook_path.exists() and not managed:
        if local_hook_path.exists():
            raise RuntimeError(
                f"Cannot install managed {spec.name} hook: {local_hook_path} already "
                "exists while current hook is unmanaged. Resolve manually."
            )
        if dry_run:
            print(f"[dry-run] would move {hook_path} -> {local_hook_path}")
        else:
            hook_path.rename(local_hook_path)
            ensure_executable(local_hook_path)
    elif local_hook_path.exists() and not dry_run:
        ensure_executable(local_hook_path)

    wrapper = render_wrapper(spec)
    if dry_run:
        print(f"[dry-run] would write {hook_path}")
        return hook_path

    hook_path.write_text(wrapper, encoding="utf-8")
    ensure_executable(hook_path)
    return hook_path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo_root = Path(args.repo_root).resolve()

    installed: list[Path] = []
    for spec in HOOK_SPECS:
        installed.append(install_hook(repo_root, spec, dry_run=args.dry_run))

    if args.dry_run:
        for hook_path in installed:
            print(f"[dry-run] managed hook target: {hook_path}")
    else:
        for hook_path in installed:
            print(f"Installed managed hook: {hook_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
