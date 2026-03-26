#!/usr/bin/env python3
"""Verify entropy-tripwire behavior before allowing push workflows."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Sequence


DEFAULT_EXCLUDES = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".codex-home",
    ".codex-local",
    "mdview.egg-info",
    "__pycache__",
    "bin/codex-local",
    "README-LOCAL-Start-Codex.md",
}

SCANNER_SCHEMA_VERSION = "1.0.0"


class TripwireError(RuntimeError):
    """Raised when any tripwire condition fails."""


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate entropy tripwire integrity: sentinel detection, clean "
            "harness run, and full scan coverage."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Repository root to validate.",
    )
    parser.add_argument(
        "--tripwire-path",
        default="tests/test_entropy_check.py",
        help="Sentinel file expected to trigger entropy findings.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print command output for all checks.",
    )
    return parser.parse_args(argv)


def path_is_excluded(path: Path, patterns: Sequence[str]) -> bool:
    as_posix = path.as_posix()
    parts = set(path.parts)
    for pattern in patterns:
        normalized = pattern.lstrip("./")
        if pattern in parts:
            return True
        if normalized and as_posix.endswith(normalized):
            return True
        if fnmatch.fnmatch(as_posix, pattern):
            return True
    return False


def iter_files(paths: Iterable[Path], excludes: Sequence[str]) -> Iterable[Path]:
    for root in paths:
        if root.is_file():
            if not path_is_excluded(root, excludes):
                yield root
            continue
        if not root.exists():
            continue

        for current_root, dirnames, filenames in os.walk(root):
            current_path = Path(current_root)
            dirnames[:] = [
                name
                for name in dirnames
                if not path_is_excluded(current_path / name, excludes)
            ]
            for filename in filenames:
                candidate = current_path / filename
                if not path_is_excluded(candidate, excludes):
                    yield candidate


def expected_scan_count(repo_root: Path, extra_excludes: Sequence[str]) -> int:
    excludes = list(DEFAULT_EXCLUDES) + list(extra_excludes)
    return sum(1 for _ in iter_files([repo_root], excludes))


def run_command(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def parse_report(output: str, label: str) -> Dict[str, object]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise TripwireError(f"Could not parse {label} JSON output: {error}") from error
    if not isinstance(payload, dict):
        raise TripwireError(f"{label} JSON output is not an object.")
    if payload.get("schema_version") != SCANNER_SCHEMA_VERSION:
        raise TripwireError(
            f"{label} schema_version mismatch: expected "
            f"{SCANNER_SCHEMA_VERSION}, got {payload.get('schema_version')}."
        )
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise TripwireError(f"{label} JSON output missing summary object.")
    return payload


def parse_summary_counts(
    payload: Dict[str, object], label: str
) -> tuple[int, int, int]:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise TripwireError(f"{label} JSON output missing summary object.")
    scanned = summary.get("scanned_files")
    flagged = summary.get("flagged_files")
    lines = summary.get("reported_high_entropy_lines")
    if (
        not isinstance(scanned, int)
        or not isinstance(flagged, int)
        or not isinstance(lines, int)
    ):
        raise TripwireError(f"{label} JSON summary fields have invalid types.")
    return scanned, flagged, lines


def result_paths(payload: Dict[str, object]) -> list[str]:
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    paths: list[str] = []
    for entry in results:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if isinstance(path, str):
            paths.append(path.replace("\\", "/"))
    return paths


def emit_step(label: str, passed: bool, detail: str) -> None:
    status = "PASS" if passed else "FAIL"
    print(f"[entropy-tripwire] {status}: {label} - {detail}")


def verify(repo_root: Path, tripwire_path: str, verbose: bool = False) -> None:
    tool_root = Path(__file__).resolve().parents[2]
    scanner = tool_root / "dev-utils" / "security" / "entropy-check.py"
    harness = tool_root / "dev-utils" / "security" / "run_entropy_harness.py"
    sentinel = tripwire_path.replace("\\", "/")

    direct = run_command(
        [sys.executable, str(scanner), "--json-output", str(repo_root)],
        cwd=tool_root,
    )
    direct_output = (direct.stdout or "") + (direct.stderr or "")
    direct_report = parse_report(direct.stdout or "", "raw scan")
    direct_scanned, _direct_flagged, _direct_lines = parse_summary_counts(
        direct_report, "raw scan"
    )
    expected_direct = expected_scan_count(repo_root, extra_excludes=[])

    if verbose:
        print(direct_output.rstrip())

    if direct.returncode != 1:
        emit_step(
            "tripwire detection", False, "raw scan did not return finding exit code"
        )
        raise TripwireError(
            "Raw entropy scan failed to produce expected non-zero result."
        )
    if not any(path.endswith(sentinel) for path in result_paths(direct_report)):
        emit_step("tripwire detection", False, "sentinel file was not reported")
        raise TripwireError("Sentinel tripwire file was not detected.")
    emit_step("tripwire detection", True, f"sentinel file `{sentinel}` detected")

    if direct_scanned != expected_direct:
        emit_step(
            "scan coverage",
            False,
            f"raw scan count {direct_scanned} != expected {expected_direct}",
        )
        raise TripwireError("Raw scan did not cover expected repository files.")
    emit_step("scan coverage", True, f"raw scan covered {direct_scanned} files")

    harness_result = run_command(
        [sys.executable, str(harness), "--json-output", str(repo_root)],
        cwd=tool_root,
    )
    harness_output = (harness_result.stdout or "") + (harness_result.stderr or "")
    harness_report = parse_report(harness_result.stdout or "", "harness scan")
    harness_scanned, harness_flagged, harness_lines = parse_summary_counts(
        harness_report, "harness scan"
    )
    expected_harness = expected_scan_count(repo_root, extra_excludes=[sentinel])

    if verbose:
        print(harness_output.rstrip())

    if harness_result.returncode != 0 or harness_flagged != 0 or harness_lines != 0:
        emit_step(
            "clean harness scan", False, "findings remained after sentinel exclusion"
        )
        raise TripwireError("Entropy harness reported non-sentinel findings.")
    emit_step("clean harness scan", True, "no non-sentinel findings detected")

    if harness_scanned != expected_harness:
        emit_step(
            "scan coverage",
            False,
            f"harness scan count {harness_scanned} != expected {expected_harness}",
        )
        raise TripwireError("Harness scan did not cover expected repository files.")
    emit_step("scan coverage", True, f"harness scan covered {harness_scanned} files")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo_root = Path(args.repo_root).resolve()

    try:
        verify(
            repo_root=repo_root, tripwire_path=args.tripwire_path, verbose=args.verbose
        )
    except TripwireError as error:
        print(f"[entropy-tripwire] FAIL: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # pragma: no cover - defensive guardrail
        print(f"[entropy-tripwire] ERROR: {error}", file=sys.stderr)
        return 2

    print("[entropy-tripwire] PASS: tripwire verification complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
