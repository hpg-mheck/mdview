"""Run standard quality tools with timeout enforcement."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple


CONFIG_FILE = Path(__file__).resolve().with_name("tool_timeouts.json")
MANDATORY_TOOL_MODULES = {"black", "pytest", "ruff"}


def _load_config() -> Dict[str, object]:
    with CONFIG_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("timeout configuration must be a JSON object")
    return data


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a configured tool command with a timeout bailout."
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Override timeout in seconds for this invocation.",
    )
    parser.add_argument(
        "tool", help="Configured tool key in scripts/tool_timeouts.json"
    )
    parsed, tool_args = parser.parse_known_args()
    parsed.tool_args = tool_args
    return parsed


def _resolve_tool_run(
    config: Dict[str, object],
    tool: str,
    override_timeout: int | None,
    tool_args: List[str],
) -> Tuple[List[str], int, int, List[str]]:
    tools = config.get("tools")
    if not isinstance(tools, dict):
        raise ValueError("configuration must include a 'tools' object")

    entry = tools.get(tool)
    if not isinstance(entry, dict):
        available = ", ".join(sorted(tools))
        raise KeyError(f"unknown tool '{tool}'. Available tools: {available}")

    command = entry.get("command")
    if not isinstance(command, list) or not all(
        isinstance(part, str) for part in command
    ):
        raise ValueError(f"tool '{tool}' must define command as a list of strings")

    timeout = override_timeout
    if timeout is None:
        configured_timeout = entry.get("timeout_seconds")
        if isinstance(configured_timeout, int) and configured_timeout > 0:
            timeout = configured_timeout
        else:
            default_timeout = config.get("default_timeout_seconds")
            if not isinstance(default_timeout, int) or default_timeout <= 0:
                raise ValueError("default_timeout_seconds must be a positive integer")
            timeout = default_timeout

    if timeout <= 0:
        raise ValueError("timeout must be a positive integer")

    retries = entry.get("timeout_retries", 0)
    if not isinstance(retries, int) or retries < 0:
        raise ValueError("timeout_retries must be a non-negative integer")

    cleanup_patterns = entry.get("cleanup_patterns", [])
    if not isinstance(cleanup_patterns, list) or not all(
        isinstance(pattern, str) for pattern in cleanup_patterns
    ):
        raise ValueError("cleanup_patterns must be a list of strings")

    args = list(tool_args)
    if args and args[0] == "--":
        args = args[1:]

    return command + args, timeout, retries, cleanup_patterns


def _bind_python_command(command: List[str]) -> List[str]:
    if command and command[0] == "python":
        return [sys.executable] + command[1:]
    return command


def _require_installed_tool(tool: str, command: List[str]) -> None:
    if tool not in MANDATORY_TOOL_MODULES:
        return
    if len(command) < 3 or command[1] != "-m":
        return

    module_name = command[2]
    if importlib.util.find_spec(module_name) is not None:
        return

    raise RuntimeError(
        "Required tool '{tool}' is not installed for interpreter '{python}'. "
        "Run ./scripts/install_prerequisites.sh, then invoke checks with "
        ".venv/bin/python or an activated .venv.".format(
            tool=tool, python=sys.executable
        )
    )


def _cleanup_processes(patterns: List[str]) -> None:
    if not patterns:
        return
    if os.name != "posix":
        return

    for pattern in patterns:
        try:
            subprocess.run(["pkill", "-f", pattern], check=False)
            print(f"[timeout-wrapper] cleanup attempted for pattern: {pattern}")
        except FileNotFoundError:
            print("[timeout-wrapper] cleanup skipped; pkill not available.")
            return


def main() -> int:
    args = _parse_args()
    config = _load_config()
    command, timeout, retries, cleanup_patterns = _resolve_tool_run(
        config=config,
        tool=args.tool,
        override_timeout=args.timeout_seconds,
        tool_args=args.tool_args,
    )
    command = _bind_python_command(command)
    try:
        _require_installed_tool(args.tool, command)
    except RuntimeError as error:
        print(f"[timeout-wrapper] prerequisite failure: {error}", file=sys.stderr)
        return 127

    pretty = " ".join(shlex.quote(part) for part in command)
    print(f"[timeout-wrapper] running: {pretty}")
    print(f"[timeout-wrapper] timeout: {timeout}s")

    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(command, check=False, timeout=timeout)
            return result.returncode
        except subprocess.TimeoutExpired:
            print(
                f"[timeout-wrapper] timeout exceeded after {timeout}s "
                f"(attempt {attempt}/{attempts}).",
                file=sys.stderr,
            )
            if attempt >= attempts:
                print(
                    "[timeout-wrapper] no retries remain. Review scope or raise "
                    "--timeout-seconds for justified runs.",
                    file=sys.stderr,
                )
                return 124
            print("[timeout-wrapper] attempting cleanup before retry.")
            _cleanup_processes(cleanup_patterns)

    return 124


if __name__ == "__main__":
    raise SystemExit(main())
