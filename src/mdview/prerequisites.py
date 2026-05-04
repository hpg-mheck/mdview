"""Prerequisite validation helpers for mdview execution."""

from __future__ import annotations

import importlib.util
import sys
from typing import Iterable, List


def _missing_dependency(module_name: str) -> bool:
    """Return True when the given module cannot be imported."""

    return importlib.util.find_spec(module_name) is None


def detect_prerequisite_issues() -> List[str]:
    """Return human-readable descriptions of missing prerequisites."""

    issues: List[str] = []
    if _missing_dependency("prompt_toolkit"):
        issues.append(
            "prompt_toolkit is not installed; run ./install.sh --mode dev "
            "(or the compatibility wrappers ./bootstrap.sh or "
            "scripts/install_prerequisites.sh) or install the package to "
            "enable interactive paging."
        )
    if _missing_dependency("rich"):
        issues.append(
            "rich is not installed; run ./install.sh --mode dev (or the "
            "compatibility wrappers ./bootstrap.sh or "
            "scripts/install_prerequisites.sh) or install the package to "
            "enable styled Markdown output."
        )
    return issues


def report_prerequisite_issues(issues: Iterable[str]) -> None:
    """Print prerequisite warnings to stderr when any are present."""

    issue_list = list(issues)
    if not issue_list:
        return

    print("mdview: environment checks detected potential problems:", file=sys.stderr)
    for issue in issue_list:
        print(f"  - {issue}", file=sys.stderr)
