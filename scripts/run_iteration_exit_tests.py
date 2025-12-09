"""Command-line driver for the iteration exit test suite.

Run this script to execute the dedicated iteration exit tests, emit dependency
warnings, and optionally persist structured reports.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from mdview.iteration_exit import run_iteration_exit_suite, write_summary


def build_parser() -> argparse.ArgumentParser:
    """Return an argument parser for the iteration exit test driver."""

    parser = argparse.ArgumentParser(
        description="Run the Codex iteration exit pytest suite with reporting."
    )
    parser.add_argument(
        "--junitxml",
        dest="junitxml",
        type=Path,
        help="Optional path for writing a JUnit XML report.",
    )
    parser.add_argument(
        "--summary-json",
        dest="summary_json",
        type=Path,
        help="Optional path for persisting a JSON summary of the run.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Additional arguments forwarded to pytest.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the iteration exit suite and emit structured reports."""

    parser = build_parser()
    args = parser.parse_args(argv)

    report = run_iteration_exit_suite(
        report_file=args.junitxml,
        extra_pytest_args=args.pytest_args,
    )

    if args.summary_json:
        write_summary(report, args.summary_json)

    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
