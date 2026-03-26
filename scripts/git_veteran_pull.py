#!/usr/bin/env python3
"""Standardized safe pull workflow for repository maintenance."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a guarded pull operation: clean-tree check, fetch/prune, "
            "fast-forward pull, and optional entropy scan."
        )
    )
    parser.add_argument(
        "--remote",
        default=None,
        help="Optional remote to pull from (defaults to git pull upstream config).",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Optional branch to pull from (requires --remote).",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow pull even when local working tree is dirty.",
    )
    parser.add_argument(
        "--skip-entropy-check",
        action="store_true",
        help="Skip post-pull entropy check.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned commands without mutating git state.",
    )
    return parser.parse_args(argv)


def run(
    command: Sequence[str], cwd: Path, dry_run: bool = False
) -> subprocess.CompletedProcess[str]:
    print(f"[git-veteran-pull] -> {' '.join(command)}")
    if dry_run:
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def ensure_ok(result: subprocess.CompletedProcess[str], context: str) -> None:
    if result.returncode == 0:
        return
    details = (result.stderr or result.stdout or "").strip()
    raise RuntimeError(f"{context} failed (exit {result.returncode}): {details}")


def repo_root_from_cwd(cwd: Path, dry_run: bool = False) -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, dry_run=dry_run)
    ensure_ok(result, "resolve repository root")
    if dry_run:
        return cwd
    return Path((result.stdout or "").strip()).resolve()


def ensure_clean_tree(repo_root: Path, dry_run: bool = False) -> None:
    result = run(["git", "status", "--porcelain"], cwd=repo_root, dry_run=dry_run)
    ensure_ok(result, "inspect working tree")
    if dry_run:
        return
    if (result.stdout or "").strip():
        raise RuntimeError("Working tree is dirty. Commit/stash or use --allow-dirty.")


def run_pull(
    repo_root: Path, remote: str | None, branch: str | None, dry_run: bool = False
) -> None:
    if branch and not remote:
        raise RuntimeError("--branch requires --remote.")

    ensure_ok(
        run(["git", "fetch", "--all", "--prune"], cwd=repo_root, dry_run=dry_run),
        "git fetch --all --prune",
    )

    pull_cmd = ["git", "pull", "--ff-only"]
    if remote:
        pull_cmd.append(remote)
    if branch:
        pull_cmd.append(branch)
    ensure_ok(run(pull_cmd, cwd=repo_root, dry_run=dry_run), "git pull --ff-only")


def run_entropy_check(repo_root: Path, dry_run: bool = False) -> None:
    ensure_ok(
        run(
            [sys.executable, "scripts/run_tool_with_timeout.py", "entropy_check"],
            cwd=repo_root,
            dry_run=dry_run,
        ),
        "post-pull entropy check",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    start_cwd = Path.cwd()

    try:
        if args.branch and not args.remote:
            raise RuntimeError("--branch requires --remote.")
        repo_root = repo_root_from_cwd(start_cwd, dry_run=args.dry_run)
        if not args.allow_dirty:
            ensure_clean_tree(repo_root, dry_run=args.dry_run)
        run_pull(repo_root, args.remote, args.branch, dry_run=args.dry_run)
        if not args.skip_entropy_check:
            run_entropy_check(repo_root, dry_run=args.dry_run)
    except RuntimeError as error:
        print(f"[git-veteran-pull] FAIL: {error}", file=sys.stderr)
        return 1

    print("[git-veteran-pull] PASS: pull workflow completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
