import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "run_tool_with_timeout.py"
)
SPEC = importlib.util.spec_from_file_location("run_tool_with_timeout", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
run_tool_with_timeout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_tool_with_timeout)


def test_bind_python_command_uses_current_interpreter() -> None:
    command = run_tool_with_timeout._bind_python_command(["python", "-m", "pytest"])

    assert command[0] == sys.executable
    assert command[1:] == ["-m", "pytest"]


def test_require_installed_tool_raises_for_missing_module(monkeypatch) -> None:
    monkeypatch.setattr(
        run_tool_with_timeout.importlib.util,
        "find_spec",
        lambda name: None if name == "pytest" else object(),
    )

    with pytest.raises(RuntimeError, match="Required tool 'pytest'"):
        run_tool_with_timeout._require_installed_tool(
            "pytest", [sys.executable, "-m", "pytest"]
        )


def test_require_installed_tool_ignores_nonmandatory_commands(monkeypatch) -> None:
    monkeypatch.setattr(
        run_tool_with_timeout.importlib.util, "find_spec", lambda name: None
    )

    run_tool_with_timeout._require_installed_tool(
        "compileall", [sys.executable, "-m", "compileall"]
    )


def test_split_black_command_keeps_options_with_values_in_base() -> None:
    base, paths = run_tool_with_timeout._split_black_command(
        [
            sys.executable,
            "-m",
            "black",
            "--target-version",
            "py39",
            "--line-length=88",
            "src",
            "tests",
        ]
    )

    assert base == [
        sys.executable,
        "-m",
        "black",
        "--target-version",
        "py39",
        "--line-length=88",
    ]
    assert paths == ["src", "tests"]


def test_codex_serial_black_requires_constrained_multi_path_env(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_CI", "1")
    monkeypatch.setenv("CODEX_MANAGED_BY_NPM", "1")
    monkeypatch.setenv("CODEX_SANDBOX_NETWORK_DISABLED", "1")

    assert run_tool_with_timeout._codex_serial_black_required(2)
    assert not run_tool_with_timeout._codex_serial_black_required(1)

    monkeypatch.delenv("CODEX_SANDBOX_NETWORK_DISABLED")

    assert not run_tool_with_timeout._codex_serial_black_required(2)


def test_maybe_run_black_serial_runs_discovered_paths(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_CI", "1")
    monkeypatch.setenv("CODEX_MANAGED_BY_NPM", "1")
    monkeypatch.setenv("CODEX_SANDBOX_NETWORK_DISABLED", "1")
    monkeypatch.setattr(
        run_tool_with_timeout,
        "discover_black_paths",
        lambda _cwd, paths: ["src/a.py", "tests/b.py"],
    )
    calls: list[list[str]] = []

    def fake_run(command, *, timeout, retries, cleanup_patterns):
        calls.append(command)
        assert timeout == 9
        assert retries == 1
        assert cleanup_patterns == ["black"]
        return 0

    monkeypatch.setattr(run_tool_with_timeout, "_run_command_with_timeout", fake_run)

    result = run_tool_with_timeout._maybe_run_black_serial(
        [sys.executable, "-m", "black", "src", "tests"],
        timeout=9,
        retries=1,
        cleanup_patterns=["black"],
    )

    assert result == 0
    assert calls == [
        [sys.executable, "-m", "black", "src/a.py"],
        [sys.executable, "-m", "black", "tests/b.py"],
    ]
