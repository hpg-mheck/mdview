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
