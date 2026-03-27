#!/usr/bin/env python3
"""Project harness for entropy-based secret scanning."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence


DEFAULT_EXCLUDES = [
    "TheKnowledge",
    "tests/test_entropy_check.py",
]


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the entropy scanner with project defaults that avoid known "
            "intentional test fixtures."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to scan (default: repository root).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Additional exclude pattern for entropy-check.py.",
    )
    parser.add_argument(
        "--top-percent",
        type=float,
        default=1.0,
        help="Top entropy percent clipped before baseline is calculated.",
    )
    parser.add_argument(
        "--spike-percent",
        type=float,
        default=20.0,
        help="Percent above clipped baseline required to flag a line.",
    )
    parser.add_argument(
        "--min-line-length",
        type=int,
        default=None,
        help="Optional minimum line length override.",
    )
    parser.add_argument(
        "--min-token-length",
        type=int,
        default=20,
        help="Minimum token length for token-level entropy checks.",
    )
    parser.add_argument(
        "--max-findings-per-file",
        type=int,
        default=20,
        help="Maximum number of findings emitted per file.",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Forward --json-output to entropy-check.py.",
    )
    return parser.parse_args(argv)


def build_command(repo_root: Path, args: argparse.Namespace) -> list[str]:
    checker = repo_root / "dev-utils" / "security" / "entropy-check.py"
    command: list[str] = [
        sys.executable,
        str(checker),
        *args.paths,
        "--top-percent",
        str(args.top_percent),
        "--spike-percent",
        str(args.spike_percent),
        "--min-token-length",
        str(args.min_token_length),
        "--max-findings-per-file",
        str(args.max_findings_per_file),
    ]
    if args.min_line_length is not None:
        command.extend(["--min-line-length", str(args.min_line_length)])
    if args.json_output:
        command.append("--json-output")

    for pattern in DEFAULT_EXCLUDES + list(args.exclude):
        command.extend(["--exclude", pattern])
    return command


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo_root = Path(__file__).resolve().parents[2]
    command = build_command(repo_root, args)
    result = subprocess.run(command, cwd=repo_root, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
