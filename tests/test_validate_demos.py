from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "validate_demos.py"
TIMEOUTS = ROOT / "scripts" / "tool_timeouts.json"
SPEC = importlib.util.spec_from_file_location("validate_demos", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validate_demos = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validate_demos
SPEC.loader.exec_module(validate_demos)


def _run(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(project_root), *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    (project / "demos").mkdir(parents=True)
    return project


def _write_demo(project: Path, text: str, name: str = "table-demo.md") -> Path:
    target = project / "demos" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def test_demo_validator_uses_cache_for_unchanged_files(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _write_demo(
        project,
        "\n".join(
            [
                "# Demo",
                "",
                "| Name | State |",
                "| :--- | :---- |",
                '| alpha | <span style="color: red">HOT</span> |',
                "",
            ]
        ),
    )

    first = _run(project)
    assert first.returncode == 0
    assert "PASS: table-demo.md" in first.stdout

    second = _run(project)
    assert second.returncode == 0
    assert "SKIP: table-demo.md" in second.stdout

    cache = validate_demos.resolve_cache_path(
        project,
        ".git/mdview-demo-validation-cache.json",
    )
    assert cache.is_file()


def test_demo_validator_invalidates_when_demo_changes(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    demo = _write_demo(
        project,
        "\n".join(
            [
                "# Demo",
                "",
                "Start state.",
                "",
            ]
        ),
    )

    first = _run(project)
    assert first.returncode == 0
    assert "PASS: table-demo.md" in first.stdout

    demo.write_text("# Demo\n\nChanged state.\n", encoding="utf-8")
    second = _run(project)
    assert second.returncode == 0
    assert "PASS: table-demo.md" in second.stdout
    assert "SKIP: table-demo.md" not in second.stdout


def test_demo_validator_reports_unclosed_fence_as_error(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _write_demo(
        project,
        "# Broken\n\n```bash\n./mdview demos/table-demo.md\n",
        name="broken-demo.md",
    )

    result = _run(project)

    assert result.returncode == 1
    assert "unclosed fenced code block" in result.stderr


def test_demo_validator_uses_gitdir_when_git_is_a_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    git_dir = project / ".git-worktree"
    git_dir.mkdir(parents=True)
    project.mkdir(parents=True, exist_ok=True)
    (project / ".git").write_text("gitdir: .git-worktree\n", encoding="utf-8")
    (project / "demos").mkdir(parents=True, exist_ok=True)
    (project / "demos" / "table-demo.md").write_text(
        "# Demo\n\nText.\n",
        encoding="utf-8",
    )

    result = _run(project)

    assert result.returncode == 0
    assert (git_dir / "mdview-demo-validation-cache.json").exists()


def test_timeout_wrapper_config_includes_demo_check() -> None:
    config = json.loads(TIMEOUTS.read_text(encoding="utf-8"))
    assert config["tools"]["demo_check"]["command"] == [
        "python",
        "scripts/validate_demos.py",
    ]
