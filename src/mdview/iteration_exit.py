"""Iteration exit testing helpers and driver utilities.

The helpers assemble a dedicated pytest suite for iteration close-out, report
missing optional dependencies, and emit structured summaries that can be stored
alongside iteration notes.
"""

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

OPTIONAL_DEPENDENCIES = {
    "rich": "Rich-based Markdown rendering and styling",
    "prompt_toolkit": "prompt_toolkit pager navigation and hyperlink focus",
}


@dataclass
class DependencyStatus:
    """Record the availability of an optional dependency."""

    name: str
    description: str
    available: bool

    def warning(self) -> Optional[str]:
        """Return a warning string when the dependency is unavailable."""

        if self.available:
            return None
        return f"{self.name} unavailable: falling back from {self.description}."


@dataclass
class IterationExitReport:
    """Summarize a single iteration exit test run."""

    exit_code: int
    missing_dependencies: List[DependencyStatus]
    warnings: List[str]
    report_file: Optional[Path] = None


SUITE_PATH = Path(__file__).resolve().parent.parent / "tests" / "iteration_exit"


def detect_dependencies() -> List[DependencyStatus]:
    """Return dependency statuses for the iteration exit suite."""

    statuses: List[DependencyStatus] = []
    for name, description in OPTIONAL_DEPENDENCIES.items():
        available = importlib.util.find_spec(name) is not None
        statuses.append(
            DependencyStatus(name=name, description=description, available=available)
        )
    return statuses


def collect_warnings(statuses: Iterable[DependencyStatus]) -> List[str]:
    """Return human-readable warnings for missing optional dependencies."""

    warnings: List[str] = []
    for status in statuses:
        warning = status.warning()
        if warning:
            warnings.append(warning)
    return warnings


def _build_pytest_args(
    report_file: Optional[Path], extra_pytest_args: Optional[Sequence[str]]
) -> List[str]:
    """Assemble pytest arguments for running the iteration exit suite."""

    args: List[str] = [str(SUITE_PATH), "-q"]
    if report_file:
        args.append(f"--junitxml={report_file}")
    if extra_pytest_args:
        args.extend(extra_pytest_args)
    return args


def run_iteration_exit_suite(
    report_file: Optional[Path] = None,
    extra_pytest_args: Optional[Sequence[str]] = None,
    pytest_runner: Optional[Callable[[Sequence[str]], int]] = None,
    stderr: Optional[object] = None,
) -> IterationExitReport:
    """Execute the iteration exit pytest suite with dependency reporting."""

    stderr_stream = stderr or sys.stderr
    statuses = detect_dependencies()
    warnings = collect_warnings(statuses)

    for warning in warnings:
        print(f"WARNING: {warning}", file=stderr_stream)

    if pytest_runner is None:
        import pytest

        pytest_runner = pytest.main

    args = _build_pytest_args(
        report_file=report_file, extra_pytest_args=extra_pytest_args
    )
    exit_code = int(pytest_runner(args))

    missing = [status for status in statuses if not status.available]
    return IterationExitReport(
        exit_code=exit_code,
        missing_dependencies=missing,
        warnings=warnings,
        report_file=Path(report_file) if report_file else None,
    )


def write_summary(report: IterationExitReport, destination: Path) -> None:
    """Persist a JSON summary of the iteration exit test run."""

    payload = {
        "exit_code": report.exit_code,
        "missing_dependencies": [
            {"name": status.name, "description": status.description}
            for status in report.missing_dependencies
        ],
        "warnings": report.warnings,
        "report_file": str(report.report_file) if report.report_file else None,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2))
