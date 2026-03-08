#!/usr/bin/env python3
"""Standardized commit-and-push workflow with entropy tripwire gating."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stage, commit, and push using repository standards. Push is "
            "blocked unless cached quality-gate verification passes."
        )
    )
    parser.add_argument(
        "-m",
        "--message",
        required=True,
        help="Commit message for `git commit -m`.",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Remote name for push (default: origin).",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Branch to push. Defaults to current branch.",
    )
    parser.add_argument(
        "--no-stage-all",
        action="store_true",
        help="Do not run `git add -A` before commit.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow empty commits by passing `--allow-empty` to git commit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned commands without mutating git state.",
    )
    parser.add_argument(
        "--no-quality-cache",
        action="store_true",
        help="Ignore quality-gate cache and rerun all checks.",
    )
    return parser.parse_args(argv)


def run(
    command: Sequence[str], cwd: Path, dry_run: bool = False
) -> subprocess.CompletedProcess[str]:
    print(f"[git-standard-commit-push] -> {' '.join(command)}")
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


def current_branch(repo_root: Path, dry_run: bool = False) -> str:
    if dry_run:
        return "DRY_RUN_BRANCH"
    result = run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
        dry_run=dry_run,
    )
    ensure_ok(result, "determine current branch")
    branch = (result.stdout or "").strip() or "HEAD"
    if branch == "HEAD":
        raise RuntimeError("Detached HEAD is not supported for standard push workflow.")
    return branch


def run_quality_gate(
    repo_root: Path, no_cache: bool = False, dry_run: bool = False
) -> None:
    command = [sys.executable, "scripts/run_quality_gate_cached.py"]
    if no_cache:
        command.append("--no-cache")
    result = run(command, cwd=repo_root, dry_run=dry_run)
    ensure_ok(result, "quality gate")


def ensure_staged_changes(repo_root: Path, dry_run: bool = False) -> None:
    result = run(["git", "diff", "--cached", "--quiet"], cwd=repo_root, dry_run=dry_run)
    if dry_run:
        return
    if result.returncode == 0:
        raise RuntimeError("No staged changes found after staging step.")
    if result.returncode != 1:
        ensure_ok(result, "inspect staged diff")


def repo_root_from_cwd(cwd: Path, dry_run: bool = False) -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, dry_run=dry_run)
    ensure_ok(result, "resolve repository root")
    if dry_run:
        return cwd
    return Path((result.stdout or "").strip()).resolve()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    start_cwd = Path.cwd()

    try:
        repo_root = repo_root_from_cwd(start_cwd, dry_run=args.dry_run)
        run_quality_gate(
            repo_root,
            no_cache=args.no_quality_cache,
            dry_run=args.dry_run,
        )

        if not args.no_stage_all:
            ensure_ok(
                run(["git", "add", "-A"], cwd=repo_root, dry_run=args.dry_run),
                "git add -A",
            )

        if not args.allow_empty:
            ensure_staged_changes(repo_root, dry_run=args.dry_run)

        commit_command = ["git", "commit", "-m", args.message]
        if args.allow_empty:
            commit_command.append("--allow-empty")
        ensure_ok(
            run(commit_command, cwd=repo_root, dry_run=args.dry_run), "git commit"
        )

        branch = args.branch or current_branch(repo_root, dry_run=args.dry_run)
        ensure_ok(
            run(
                ["git", "push", args.remote, branch],
                cwd=repo_root,
                dry_run=args.dry_run,
            ),
            "git push",
        )
    except RuntimeError as error:
        print(f"[git-standard-commit-push] FAIL: {error}", file=sys.stderr)
        return 1

    print("[git-standard-commit-push] PASS: commit and push completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
