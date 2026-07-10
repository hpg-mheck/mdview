from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import scripts.git_standard_commit_push as git_standard_commit_push
from scripts.git_standard_commit_push import (
    build_commit_command,
    pending_commit_changes_path,
    pending_commit_changes_text,
)

ROOT = Path(__file__).resolve().parent.parent
COMMIT_PUSH = ROOT / "scripts" / "git_standard_commit_push.py"
VETERAN_PULL = ROOT / "scripts" / "git_veteran_pull.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_git_standard_commit_push_rejects_missing_message() -> None:
    result = _run(COMMIT_PUSH)
    assert result.returncode == 2


def test_git_veteran_pull_rejects_branch_without_remote() -> None:
    result = _run(VETERAN_PULL, "--branch", "trunk")
    assert result.returncode == 1
    assert "--branch requires --remote." in result.stderr


def test_git_standard_commit_push_dry_run_succeeds() -> None:
    result = _run(COMMIT_PUSH, "--dry-run", "-m", "test message")
    assert result.returncode == 0
    assert "Files about to stage:" in result.stdout
    assert result.stdout.index("git diff") < result.stdout.index("git add -A")
    assert result.stdout.index("git diff --cached") < result.stdout.index("git commit")


def test_ensure_explicit_git_identity_requires_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command, cwd, dry_run=False):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(git_standard_commit_push, "run", fake_run)

    try:
        git_standard_commit_push.ensure_explicit_git_identity(
            tmp_path,
            environment={},
        )
    except RuntimeError as error:
        assert "not explicitly configured" in str(error)
        assert "Never infer addresses" in str(error)
    else:
        raise AssertionError("expected missing-identity failure")

    assert calls == [
        ["git", "config", "--get", "user.name"],
        ["git", "config", "--get", "user.email"],
    ]


def test_ensure_explicit_git_identity_rejects_partial_author_environment(
    tmp_path: Path,
) -> None:
    try:
        git_standard_commit_push.ensure_explicit_git_identity(
            tmp_path,
            environment={"GIT_AUTHOR_EMAIL": "test@example.com"},
        )
    except RuntimeError as error:
        assert "Explicit git author identity is incomplete" in str(error)
    else:
        raise AssertionError("expected partial-author failure")


def test_ensure_explicit_git_identity_allows_explicit_committer_for_author(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command, cwd, dry_run=False):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(git_standard_commit_push, "run", fake_run)

    git_standard_commit_push.ensure_explicit_git_identity(
        tmp_path,
        environment={
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )

    assert calls == [
        ["git", "config", "--get", "user.name"],
        ["git", "config", "--get", "user.email"],
    ]


def test_stage_path_runs_git_diff_before_git_add(
    tmp_path: Path,
    monkeypatch,
) -> None:
    file_path = tmp_path / "example.txt"
    file_path.write_text("example\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command, cwd, dry_run=False):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(git_standard_commit_push, "run", fake_run)

    git_standard_commit_push.stage_path(
        tmp_path,
        file_path,
        prompt_for_review=False,
    )

    assert calls == [
        ["git", "diff", "--", "example.txt"],
        ["git", "add", "example.txt"],
    ]


def test_review_prompt_can_pause_for_external_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(
        git_standard_commit_push,
        "git_dir",
        lambda repo_root, dry_run=False: tmp_path / ".git",
    )
    answers = iter(["1", "1"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    try:
        git_standard_commit_push.maybe_prompt_for_staging_review(
            tmp_path,
            ["M example.txt"],
        )
    except RuntimeError as error:
        assert "--assume-reviewed" in str(error)
    else:
        raise AssertionError("expected review pause")


def test_review_prompt_can_disable_for_current_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(
        git_standard_commit_push,
        "git_dir",
        lambda repo_root, dry_run=False: tmp_path / ".git",
    )
    monkeypatch.setattr(
        git_standard_commit_push,
        "shell_session_token",
        lambda: "session-1",
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "3")

    git_standard_commit_push.maybe_prompt_for_staging_review(
        tmp_path,
        ["M example.txt"],
    )

    assert (tmp_path / ".git" / "review-prompts-disabled-session-1").is_file()


def test_clear_review_prompt_state_removes_current_session_marker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    marker = git_dir / "review-prompts-disabled-session-1"
    marker.write_text("disabled\n", encoding="utf-8")
    monkeypatch.setattr(
        git_standard_commit_push,
        "git_dir",
        lambda repo_root, dry_run=False: git_dir,
    )
    monkeypatch.setattr(
        git_standard_commit_push,
        "shell_session_token",
        lambda: "session-1",
    )

    git_standard_commit_push.clear_review_prompt_state(tmp_path)

    assert not marker.exists()


def test_pending_commit_changes_path_prefers_internal_override(
    tmp_path: Path,
) -> None:
    internal = tmp_path / "internal" / "overrides" / "state"
    project_state = tmp_path / "project-management" / "state"
    internal.mkdir(parents=True)
    project_state.mkdir(parents=True)
    internal_queue = internal / "pending-commit-changes.txt"
    project_queue = project_state / "pending-commit-changes.txt"
    internal_queue.write_text("- internal\n", encoding="utf-8")
    project_queue.write_text("- project\n", encoding="utf-8")

    assert pending_commit_changes_path(tmp_path) == internal_queue


def test_pending_commit_changes_path_falls_back_to_project_management(
    tmp_path: Path,
) -> None:
    project_state = tmp_path / "project-management" / "state"
    project_state.mkdir(parents=True)
    project_queue = project_state / "pending-commit-changes.txt"
    project_queue.write_text("- project\n", encoding="utf-8")

    assert pending_commit_changes_path(tmp_path) == project_queue


def test_pending_commit_changes_text_strips_blank_lines(tmp_path: Path) -> None:
    pending_queue = tmp_path / "pending-commit-changes.txt"
    pending_queue.write_text("\n- first item\n- second item\n\n", encoding="utf-8")

    assert pending_commit_changes_text(pending_queue) == "- first item\n- second item"


def test_build_commit_command_uses_pending_queue_as_body() -> None:
    command = build_commit_command(
        "subject line",
        "- first item\n- second item",
        allow_empty=False,
    )

    assert command == [
        "git",
        "commit",
        "-m",
        "subject line",
        "-m",
        "- first item\n- second item",
    ]


def test_restore_pending_commit_changes_rewrites_and_stages_queue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    queue = tmp_path / "pending-commit-changes.txt"
    queue.write_text("", encoding="utf-8")
    staged: list[tuple[Path, bool]] = []

    def fake_stage_path(
        repo_root,
        path,
        dry_run=False,
        prompt_for_review=True,
        assume_reviewed=False,
    ):
        assert repo_root == tmp_path
        assert dry_run is False
        assert assume_reviewed is False
        staged.append((path, prompt_for_review))

    monkeypatch.setattr(git_standard_commit_push, "stage_path", fake_stage_path)

    git_standard_commit_push.restore_pending_commit_changes(
        tmp_path,
        queue,
        "- restored summary\n",
    )

    assert queue.read_text(encoding="utf-8") == "- restored summary\n"
    assert staged == [(queue, False)]
