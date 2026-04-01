from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_theknowledge_consumer_files_exist() -> None:
    required_paths = [
        ROOT / ".python-version",
        ROOT / ".gitmodules",
        ROOT / "AGENTS.md",
        ROOT / "bootstrap-stage2.py",
        ROOT / "bootstrap.sh",
        ROOT / "ECRs" / "README.md",
        ROOT / "ECRs" / "TheKnowledge" / "README.md",
        ROOT / "docs" / "development-workflow.txt",
        ROOT / "install.sh",
        ROOT / "project-management" / "git-flow.txt",
        ROOT / "python-environments.json",
        ROOT / "scripts" / "_theknowledge_delegate.py",
        ROOT / "scripts" / "dev_setup.py",
        ROOT / "scripts" / "install-stage-2.py",
        ROOT / "scripts" / "python_environment_bootstrap.py",
        ROOT / "scripts" / "refresh_managed_agents.py",
        ROOT / "scripts" / "report_managed_agents_drift.py",
        ROOT / "scripts" / "tool_validation_profiles.py",
        ROOT / "set-context-bootstrap.sh",
        ROOT / "set-context.sh",
        ROOT / "TheKnowledge" / "README.md",
        ROOT / "tool_execution_constraints.json",
        ROOT / "tool_validation_profiles.json",
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


def test_bootstrap_docs_cover_canonical_setup_path() -> None:
    texts = [
        (ROOT / "AGENTS.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "development-workflow.txt").read_text(encoding="utf-8"),
        (ROOT / "docs" / "installation.txt").read_text(encoding="utf-8"),
        (ROOT / "docs" / "running-tests.txt").read_text(encoding="utf-8"),
    ]

    for text in texts:
        assert "./install.sh" in text
        assert "bootstrap.sh" in text
        assert "scripts/install_prerequisites.sh" in text


def test_install_entrypoints_are_tracked_executable() -> None:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--stage",
            "--",
            "install.sh",
            "bootstrap.sh",
            "scripts/install_prerequisites.sh",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    modes: dict[str, str] = {}
    for line in result.stdout.splitlines():
        mode, _sha, _stage, path = line.split(maxsplit=3)
        modes[path] = mode

    assert modes == {
        "bootstrap.sh": "100755",
        "install.sh": "100755",
        "scripts/install_prerequisites.sh": "100755",
    }


def test_python_environment_config_has_bootstrap_and_runtime_contexts() -> None:
    config = json.loads((ROOT / "python-environments.json").read_text())

    assert config["bootstrap"]["required_version"] == "3.9"
    assert config["runtime"]["required_version"] == "3.12"
    assert (
        config["bootstrap"]["environment_name"] == config["bootstrap"]["base_version"]
    )
    assert config["runtime"]["environment_name"] == config["runtime"]["base_version"]
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == config[
        "runtime"
    ]["environment_name"]


def test_tool_validation_profiles_match_mdview_paths() -> None:
    config = json.loads((ROOT / "tool_validation_profiles.json").read_text())
    policies = config["runtime_policies"]
    black_tool = config["tools"]["black"]

    assert (
        "THEKNOWLEDGE_BOOTSTRAP_PYTHON"
        in policies["bootstrap_python"]["environment_variables"]
    )
    assert (
        "THEKNOWLEDGE_PYTHON_TOOLS"
        in policies["steady_state_python_tools"]["environment_variables"]
    )
    assert black_tool["default_roots"] == [
        "src",
        "tests",
        "scripts",
        "standards-and-practices/dev-utils",
        "templates/scripts",
    ]


def test_timeout_wrapper_pytest_command_stays_scoped_to_mdview_tests() -> None:
    config = json.loads((ROOT / "scripts" / "tool_timeouts.json").read_text())
    assert config["tools"]["pytest"]["command"] == ["python", "-m", "pytest", "tests"]


def test_timeout_wrapper_config_includes_demo_check() -> None:
    config = json.loads((ROOT / "scripts" / "tool_timeouts.json").read_text())
    assert config["tools"]["demo_check"]["command"] == [
        "python",
        "scripts/validate_demos.py",
    ]
