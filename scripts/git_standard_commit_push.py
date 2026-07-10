#!/usr/bin/env python3
"""Standardized commit-and-push workflow with review gates."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence

PENDING_COMMIT_CHANGES_PATHS = (
    Path("internal/overrides/state/pending-commit-changes.txt"),
    Path("project-management/state/pending-commit-changes.txt"),
)
REVIEW_PROMPT_STATE_PREFIX = "review-prompts-disabled-"


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
        help="Commit subject for `git commit -m`.",
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
    parser.add_argument(
        "--assume-reviewed",
        action="store_true",
        help="Skip the interactive pre-staging review prompt.",
    )
    parser.add_argument(
        "--resume-review-prompts",
        action="store_true",
        help="Re-enable pre-staging review prompts for the current shell session.",
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


def git_dir(repo_root: Path, dry_run: bool = False) -> Path:
    if dry_run:
        return repo_root / ".git"
    result = run(["git", "rev-parse", "--git-dir"], cwd=repo_root, dry_run=dry_run)
    ensure_ok(result, "resolve git directory")
    value = (result.stdout or "").strip()
    path = Path(value)
    if not path.is_absolute():
        path = (repo_root / path).resolve()
    return path


def run_quality_gate(
    repo_root: Path, no_cache: bool = False, dry_run: bool = False
) -> None:
    command = [sys.executable, "scripts/run_quality_gate_cached.py"]
    if no_cache:
        command.append("--no-cache")
    result = run(command, cwd=repo_root, dry_run=dry_run)
    ensure_ok(result, "quality gate")


def show_diff(
    repo_root: Path,
    relative_paths: Sequence[str] | None = None,
    dry_run: bool = False,
    cached: bool = False,
) -> None:
    command = ["git", "diff"]
    if cached:
        command.append("--cached")
    if relative_paths:
        command.extend(["--", *relative_paths])
    result = run(command, cwd=repo_root, dry_run=dry_run)
    if dry_run:
        return
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    ensure_ok(result, "git diff")


def ensure_staged_changes(repo_root: Path, dry_run: bool = False) -> None:
    result = run(["git", "diff", "--cached", "--quiet"], cwd=repo_root, dry_run=dry_run)
    if dry_run:
        return
    if result.returncode == 0:
        raise RuntimeError("No staged changes found after staging step.")
    if result.returncode != 1:
        ensure_ok(result, "inspect staged diff")


def shell_session_token() -> str:
    value = os.environ.get("THEKNOWLEDGE_REVIEW_SESSION_ID")
    if value:
        return "".join(
            char if char.isalnum() or char in {"-", "_"} else "-" for char in value
        )
    return str(os.getppid())


def review_prompt_state_path(repo_root: Path, dry_run: bool = False) -> Path:
    token = shell_session_token()
    return git_dir(repo_root, dry_run=dry_run) / f"{REVIEW_PROMPT_STATE_PREFIX}{token}"


def clear_review_prompt_state(repo_root: Path, dry_run: bool = False) -> None:
    path = review_prompt_state_path(repo_root, dry_run=dry_run)
    if dry_run:
        print(
            "[git-standard-commit-push] -> "
            f"clear review prompt state {path.as_posix()}"
        )
        return
    if path.exists():
        path.unlink()
        print(
            "[git-standard-commit-push] Review prompts re-enabled for the "
            "current shell session."
        )


def review_prompts_disabled(repo_root: Path, dry_run: bool = False) -> bool:
    if dry_run:
        return False
    return review_prompt_state_path(repo_root, dry_run=dry_run).exists()


def disable_review_prompts(repo_root: Path, dry_run: bool = False) -> None:
    path = review_prompt_state_path(repo_root, dry_run=dry_run)
    if dry_run:
        print(
            "[git-standard-commit-push] -> "
            f"write review prompt state {path.as_posix()}"
        )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("disabled\n", encoding="utf-8")
    print(
        "[git-standard-commit-push] Review prompts disabled for the current "
        "shell session. Rerun with `--resume-review-prompts` to ask again."
    )


def repo_root_from_cwd(cwd: Path, dry_run: bool = False) -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, dry_run=dry_run)
    ensure_ok(result, "resolve repository root")
    if dry_run:
        return cwd
    return Path((result.stdout or "").strip()).resolve()


def pending_commit_changes_path(repo_root: Path) -> Optional[Path]:
    for relative_path in PENDING_COMMIT_CHANGES_PATHS:
        candidate = repo_root / relative_path
        if candidate.is_file():
            return candidate
    return None


def pending_commit_changes_text(path: Optional[Path]) -> str:
    if path is None:
        return ""
    return path.read_text(encoding="utf-8").strip()


def git_config_value(
    repo_root: Path,
    key: str,
    dry_run: bool = False,
) -> Optional[str]:
    if dry_run:
        return None
    result = run(["git", "config", "--get", key], cwd=repo_root, dry_run=dry_run)
    if result.returncode == 1:
        return None
    ensure_ok(result, f"git config --get {key}")
    value = (result.stdout or "").strip()
    return value or None


def explicit_env_identity(
    environment: Mapping[str, str],
    role: str,
) -> Optional[tuple[str, str]]:
    name_key = f"GIT_{role}_NAME"
    email_key = f"GIT_{role}_EMAIL"
    name = environment.get(name_key)
    email = environment.get(email_key)
    if name is None and email is None:
        return None
    if not name or not email:
        raise RuntimeError(
            f"Explicit git {role.lower()} identity is incomplete. Set both "
            f"`{name_key}` and `{email_key}`, or unset both."
        )
    return name.strip(), email.strip()


def configured_git_identity(
    repo_root: Path,
    dry_run: bool = False,
) -> Optional[tuple[str, str]]:
    name = git_config_value(repo_root, "user.name", dry_run=dry_run)
    email = git_config_value(repo_root, "user.email", dry_run=dry_run)
    if name is None and email is None:
        return None
    if not name or not email:
        raise RuntimeError(
            "Git identity is partially configured. Set both `user.name` and "
            "`user.email`, or unset both."
        )
    return name, email


def ensure_explicit_git_identity(
    repo_root: Path,
    dry_run: bool = False,
    environment: Optional[Mapping[str, str]] = None,
) -> None:
    if dry_run:
        return
    environment = os.environ if environment is None else environment
    author = explicit_env_identity(environment, "AUTHOR")
    committer = explicit_env_identity(environment, "COMMITTER")
    configured = configured_git_identity(repo_root, dry_run=dry_run)
    resolved_author = author or committer or configured
    resolved_committer = committer or configured
    if resolved_author is not None and resolved_committer is not None:
        return
    raise RuntimeError(
        "Git commit identity is not explicitly configured. Set `git config "
        "user.name` and `git config user.email`, or set deliberate "
        "`GIT_COMMITTER_NAME`/`GIT_COMMITTER_EMAIL` values and optional "
        "separate `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL` overrides. Never "
        "infer addresses from commit history, hostnames, or network "
        "identifiers."
    )


def build_commit_command(
    message: str, pending_body: str, allow_empty: bool
) -> list[str]:
    command = ["git", "commit", "-m", message]
    if pending_body:
        command.extend(["-m", pending_body])
    if allow_empty:
        command.append("--allow-empty")
    return command


def list_stage_candidates(candidates: Sequence[str]) -> None:
    if not candidates:
        print("[git-standard-commit-push] Files about to stage: none")
        return
    print("[git-standard-commit-push] Files about to stage:")
    for candidate in candidates:
        print(f"  {candidate}")


def stage_candidates(repo_root: Path, dry_run: bool = False) -> list[str]:
    if dry_run:
        return ["DRY_RUN_CHANGESET"]
    result = run(
        ["git", "status", "--short"],
        cwd=repo_root,
        dry_run=dry_run,
    )
    ensure_ok(result, "inspect pending staging candidates")
    return [
        line.rstrip() for line in (result.stdout or "").splitlines() if line.strip()
    ]


def prompt_choice(prompt: str, valid_choices: set[str]) -> str:
    while True:
        try:
            choice = input(prompt).strip()
        except EOFError as error:
            raise RuntimeError(
                "Interactive review prompt could not read input. Rerun with "
                "`--assume-reviewed` after an explicit review decision."
            ) from error
        if choice in valid_choices:
            return choice
        print(
            "[git-standard-commit-push] Please choose one of: "
            + ", ".join(sorted(valid_choices))
        )


def launch_meld_review(
    repo_root: Path,
    relative_paths: Sequence[str] | None = None,
    dry_run: bool = False,
) -> None:
    if shutil.which("meld") is None:
        raise RuntimeError(
            "Meld is not available on PATH. Install it first or choose a "
            "different review path."
        )
    command = ["git", "difftool", "--dir-diff", "--tool=meld", "--no-prompt"]
    if relative_paths:
        command.extend(["--", *relative_paths])
    print(f"[git-standard-commit-push] -> {' '.join(command)}")
    if dry_run:
        return
    result = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Meld review failed (exit {result.returncode}).")


def maybe_prompt_for_staging_review(
    repo_root: Path,
    candidates: Sequence[str],
    relative_paths: Sequence[str] | None = None,
    dry_run: bool = False,
    assume_reviewed: bool = False,
) -> None:
    list_stage_candidates(candidates)
    if dry_run or assume_reviewed or not candidates:
        return
    if review_prompts_disabled(repo_root, dry_run=dry_run):
        print(
            "[git-standard-commit-push] Review prompt suppressed for the "
            "current shell session."
        )
        return

    choice = prompt_choice(
        "Review changes before staging? "
        "[1=file review, 2=proceed, 3=disable prompts for this session] ",
        {"1", "2", "3"},
    )
    if choice == "2":
        return
    if choice == "3":
        disable_review_prompts(repo_root, dry_run=dry_run)
        return

    review_mode = prompt_choice(
        "Review how? " "[1=file-by-file outside helper, 2=meld changeset, 3=abort] ",
        {"1", "2", "3"},
    )
    if review_mode == "1":
        raise RuntimeError(
            "Staging paused for file-by-file review. Review the changes in "
            "the conversation or with `git diff`, then rerun with "
            "`--assume-reviewed`."
        )
    if review_mode == "3":
        raise RuntimeError("Staging aborted at user request.")

    launch_meld_review(
        repo_root,
        relative_paths=relative_paths,
        dry_run=dry_run,
    )
    proceed = prompt_choice(
        "Proceed with staging after Meld review? [y/N] ",
        {"", "N", "Y", "n", "y"},
    )
    if proceed.lower() != "y":
        raise RuntimeError("Staging aborted after Meld review.")


def stage_path(
    repo_root: Path,
    path: Path,
    dry_run: bool = False,
    prompt_for_review: bool = True,
    assume_reviewed: bool = False,
) -> None:
    relative_path = path.relative_to(repo_root).as_posix()
    if prompt_for_review:
        maybe_prompt_for_staging_review(
            repo_root,
            [relative_path],
            relative_paths=[relative_path],
            dry_run=dry_run,
            assume_reviewed=assume_reviewed,
        )
    else:
        list_stage_candidates([relative_path])
    show_diff(repo_root, [relative_path], dry_run=dry_run)
    ensure_ok(
        run(["git", "add", relative_path], cwd=repo_root, dry_run=dry_run),
        f"git add {relative_path}",
    )


def clear_pending_commit_changes(path: Path, dry_run: bool = False) -> str:
    original = path.read_text(encoding="utf-8")
    if not dry_run:
        path.write_text("", encoding="utf-8")
    return original


def restore_pending_commit_changes(
    repo_root: Path, path: Path, content: str, dry_run: bool = False
) -> None:
    if not dry_run:
        path.write_text(content, encoding="utf-8")
    stage_path(
        repo_root,
        path,
        dry_run=dry_run,
        prompt_for_review=False,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    start_cwd = Path.cwd()

    try:
        repo_root = repo_root_from_cwd(start_cwd, dry_run=args.dry_run)
        if args.resume_review_prompts:
            clear_review_prompt_state(repo_root, dry_run=args.dry_run)
        ensure_explicit_git_identity(repo_root, dry_run=args.dry_run)
        pending_path = pending_commit_changes_path(repo_root)
        pending_body = pending_commit_changes_text(pending_path)
        pending_backup = ""
        run_quality_gate(
            repo_root,
            no_cache=args.no_quality_cache,
            dry_run=args.dry_run,
        )

        if not args.no_stage_all:
            maybe_prompt_for_staging_review(
                repo_root,
                stage_candidates(repo_root, dry_run=args.dry_run),
                dry_run=args.dry_run,
                assume_reviewed=args.assume_reviewed,
            )
            show_diff(repo_root, dry_run=args.dry_run)
            ensure_ok(
                run(["git", "add", "-A"], cwd=repo_root, dry_run=args.dry_run),
                "git add -A",
            )

        if pending_path is not None and pending_body:
            pending_backup = clear_pending_commit_changes(
                pending_path, dry_run=args.dry_run
            )
            try:
                stage_path(
                    repo_root,
                    pending_path,
                    dry_run=args.dry_run,
                    prompt_for_review=False,
                )
            except RuntimeError:
                restore_pending_commit_changes(
                    repo_root,
                    pending_path,
                    pending_backup,
                    dry_run=args.dry_run,
                )
                raise

        show_diff(repo_root, dry_run=args.dry_run, cached=True)
        if not args.allow_empty:
            ensure_staged_changes(repo_root, dry_run=args.dry_run)
        commit_command = build_commit_command(
            args.message, pending_body, args.allow_empty
        )
        commit_result = run(commit_command, cwd=repo_root, dry_run=args.dry_run)
        if commit_result.returncode != 0:
            if pending_path is not None and pending_body:
                restore_pending_commit_changes(
                    repo_root,
                    pending_path,
                    pending_backup,
                    dry_run=args.dry_run,
                )
            ensure_ok(commit_result, "git commit")

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
