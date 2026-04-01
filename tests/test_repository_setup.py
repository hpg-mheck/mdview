from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_theknowledge_consumer_files_exist() -> None:
    required_paths = [
        ROOT / ".gitmodules",
        ROOT / "AGENTS.md",
        ROOT / "docs" / "development-workflow.txt",
        ROOT / "project-management" / "git-flow.txt",
        ROOT / "scripts" / "_theknowledge_delegate.py",
        ROOT / "scripts" / "refresh_managed_agents.py",
        ROOT / "scripts" / "report_managed_agents_drift.py",
        ROOT / "TheKnowledge" / "README.md",
    ]

    for path in required_paths:
        assert path.exists(), f"expected setup path to exist: {path}"


def test_agents_references_theknowledge_and_local_overrides() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "TheKnowledge/AGENTS.md" in agents
    assert "project-management/state/" in agents
    assert "python scripts/report_managed_agents_drift.py" in agents
    assert "python scripts/refresh_managed_agents.py" in agents
    assert "git submodule update --init --recursive TheKnowledge" in agents


def test_agents_managed_sections_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "report_managed_agents_drift.py")],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_refresh_managed_agents_dry_run_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "refresh_managed_agents.py"),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "would refresh AGENTS.md" in result.stdout


def test_workflow_docs_cover_submodule_init_and_agents_refresh() -> None:
    development_workflow = (ROOT / "docs" / "development-workflow.txt").read_text(
        encoding="utf-8"
    )
    git_flow = (ROOT / "project-management" / "git-flow.txt").read_text(
        encoding="utf-8"
    )

    for text in (development_workflow, git_flow):
        assert "git submodule update --init --recursive TheKnowledge" in text
        assert "python scripts/report_managed_agents_drift.py" in text
        assert "python scripts/refresh_managed_agents.py" in text


def test_workflow_docs_cover_demo_check() -> None:
    texts = [
        (ROOT / "AGENTS.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "development-workflow.txt").read_text(encoding="utf-8"),
        (ROOT / "docs" / "running-tests.txt").read_text(encoding="utf-8"),
        (ROOT / "project-management" / "git-flow.txt").read_text(encoding="utf-8"),
    ]

    for text in texts:
        assert "python scripts/run_tool_with_timeout.py demo_check" in text


def test_timeout_wrapper_pytest_command_stays_scoped_to_mdview_tests() -> None:
    config = json.loads((ROOT / "scripts" / "tool_timeouts.json").read_text())
    assert config["tools"]["pytest"]["command"] == ["python", "-m", "pytest", "tests"]


def test_timeout_wrapper_config_includes_demo_check() -> None:
    config = json.loads((ROOT / "scripts" / "tool_timeouts.json").read_text())
    assert config["tools"]["demo_check"]["command"] == [
        "python",
        "scripts/validate_demos.py",
    ]
