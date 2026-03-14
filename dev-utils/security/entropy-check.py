#!/usr/bin/env python3
"""Entropy-based line scanner for potential secret material."""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


DEFAULT_EXCLUDES = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "mdview.egg-info",
    "__pycache__",
}

CODE_EXTENSIONS = {
    ".py",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".bat",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".rs",
    ".go",
    ".java",
    ".rb",
}
DOC_EXTENSIONS = {".txt", ".md", ".rst", ".adoc"}
MARKUP_EXTENSIONS = {".html", ".htm", ".xml"}
CONFIG_EXTENSIONS = {
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
}
DATA_EXTENSIONS = {".csv", ".tsv"}

ABSOLUTE_ENTROPY_FLOOR = {
    "code": 3.6,
    "docs": 3.8,
    "markup": 3.8,
    "config": 3.8,
    "data": 4.0,
    "text": 3.8,
}

MIN_LENGTH_BY_TYPE = {
    "code": 24,
    "docs": 28,
    "markup": 28,
    "config": 20,
    "data": 20,
    "text": 24,
}

TOKEN_RE = re.compile(r"[A-Za-z0-9_+\-=/]{24,}")
OUTPUT_SCHEMA_VERSION = "1.0.0"


@dataclass
class LineEntropy:
    line_number: int
    entropy: float
    text: str
    token_entropy: float | None = None
    token_preview: str | None = None


@dataclass
class FileScanResult:
    path: Path
    major_type: str
    baseline_entropy: float
    threshold_entropy: float
    findings: List[LineEntropy]


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find lines with anomalously high entropy compared to each file's "
            "top-1%-clipped baseline."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to scan (default: current directory).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help=(
            "Exclude path pattern (fnmatch). May be passed multiple times. "
            "Defaults include .git, .venv, caches, and egg-info."
        ),
    )
    parser.add_argument(
        "--top-percent",
        type=float,
        default=1.0,
        help="Top entropy percentage to clip before computing baseline.",
    )
    parser.add_argument(
        "--spike-percent",
        type=float,
        default=20.0,
        help="Percent above clipped baseline to flag lines.",
    )
    parser.add_argument(
        "--min-line-length",
        type=int,
        default=None,
        help="Global minimum line length to consider for entropy checks.",
    )
    parser.add_argument(
        "--max-findings-per-file",
        type=int,
        default=20,
        help="Maximum findings reported per file.",
    )
    parser.add_argument(
        "--min-token-length",
        type=int,
        default=20,
        help="Minimum token length for token-level entropy checks.",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help=(
            "Emit structured JSON output for machine parsing. "
            "The first key is always `schema_version`."
        ),
    )
    return parser.parse_args(argv)


def infer_major_type(path: Path, text: str) -> str:
    suffix = path.suffix.lower()
    if suffix in CODE_EXTENSIONS or text.startswith("#!"):
        return "code"
    if suffix in DOC_EXTENSIONS:
        return "docs"
    if suffix in MARKUP_EXTENSIONS:
        return "markup"
    if suffix in CONFIG_EXTENSIONS:
        return "config"
    if suffix in DATA_EXTENSIONS:
        return "data"
    return "text"


def is_binary_blob(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    sample = data[:4096]
    non_text = sum(byte < 9 or (13 < byte < 32) for byte in sample)
    return non_text / max(len(sample), 1) > 0.30


def iter_files(paths: Iterable[str], excludes: Sequence[str]) -> Iterable[Path]:
    exclude_patterns = list(DEFAULT_EXCLUDES) + list(excludes)
    roots = [Path(path).resolve() for path in paths]

    for root in roots:
        if root.is_file():
            if not path_is_excluded(root, exclude_patterns):
                yield root
            continue
        if not root.exists():
            continue

        for current_root, dirnames, filenames in os.walk(root):
            current_path = Path(current_root)
            dirnames[:] = [
                name
                for name in dirnames
                if not path_is_excluded(current_path / name, exclude_patterns)
            ]
            for filename in filenames:
                candidate = current_path / filename
                if not path_is_excluded(candidate, exclude_patterns):
                    yield candidate


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


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    entropy = 0.0
    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy


def redact_long_tokens(value: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return f"{token[:4]}...{token[-4:]}"

    return TOKEN_RE.sub(_replace, value)


def most_entropic_token(value: str, min_token_length: int) -> tuple[float, str] | None:
    pattern = re.compile(rf"[A-Za-z0-9_+\-=/]{{{min_token_length},}}")
    best: tuple[float, str] | None = None
    for match in pattern.finditer(value):
        token = match.group(0)
        entropy = shannon_entropy(token)
        if best is None or entropy > best[0]:
            best = (entropy, token)
    return best


def clip_top_percent(values: Sequence[float], top_percent: float) -> List[float]:
    if not values:
        return []
    sorted_values = sorted(values)
    if top_percent <= 0:
        return sorted_values
    trim_count = math.ceil(len(sorted_values) * (top_percent / 100.0))
    trim_count = min(trim_count, max(len(sorted_values) - 1, 0))
    if trim_count <= 0:
        return sorted_values
    return sorted_values[:-trim_count]


def scan_file(
    path: Path,
    top_percent: float,
    spike_percent: float,
    min_line_length: int | None,
    max_findings_per_file: int,
    min_token_length: int,
) -> FileScanResult | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if is_binary_blob(data):
        return None

    text = data.decode("utf-8", errors="replace")
    major_type = infer_major_type(path, text)
    min_len = min_line_length or MIN_LENGTH_BY_TYPE[major_type]
    entropy_floor = ABSOLUTE_ENTROPY_FLOOR[major_type]

    entropies: List[LineEntropy] = []
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if len(stripped) < min_len:
            continue
        entropies.append(
            LineEntropy(
                line_number=index,
                entropy=shannon_entropy(stripped),
                text=line.rstrip("\n"),
            )
        )

    if len(entropies) < 2:
        return None

    clipped_values = clip_top_percent(
        [line_entropy.entropy for line_entropy in entropies], top_percent
    )
    if not clipped_values:
        return None
    baseline = sum(clipped_values) / len(clipped_values)
    relative_threshold = baseline * (1.0 + (spike_percent / 100.0))
    threshold = max(relative_threshold, entropy_floor)

    high_entropy_lines = [
        line_entropy for line_entropy in entropies if line_entropy.entropy > threshold
    ]
    token_threshold = max(4.0, threshold)
    findings: List[LineEntropy] = []
    for candidate in high_entropy_lines:
        token_match = most_entropic_token(candidate.text, min_token_length)
        if token_match is None:
            continue
        token_entropy, token = token_match
        if token_entropy <= token_threshold:
            continue
        findings.append(
            LineEntropy(
                line_number=candidate.line_number,
                entropy=candidate.entropy,
                text=candidate.text,
                token_entropy=token_entropy,
                token_preview=redact_long_tokens(token),
            )
        )

    findings = sorted(findings, key=lambda item: item.entropy, reverse=True)[
        :max_findings_per_file
    ]
    if not findings:
        return None

    return FileScanResult(
        path=path,
        major_type=major_type,
        baseline_entropy=baseline,
        threshold_entropy=threshold,
        findings=findings,
    )


def render(results: Sequence[FileScanResult], cwd: Path) -> str:
    lines: List[str] = []
    for result in sorted(results, key=lambda item: item.path.as_posix()):
        try:
            rel = result.path.relative_to(cwd)
        except ValueError:
            rel = result.path
        lines.append(
            (
                f"{rel} [type={result.major_type}] "
                f"baseline={result.baseline_entropy:.3f} "
                f"threshold={result.threshold_entropy:.3f}"
            )
        )
        for finding in result.findings:
            preview = redact_long_tokens(finding.text.strip())
            if len(preview) > 120:
                preview = f"{preview[:72]} ... {preview[-42:]}"
            lines.append(
                (
                    f"  L{finding.line_number}: entropy={finding.entropy:.3f} "
                    f"token_entropy={finding.token_entropy:.3f} "
                    f"token={finding.token_preview} "
                    f"line={preview}"
                )
            )
    return "\n".join(lines)


def _relative_display_path(path: Path, cwd: Path) -> str:
    try:
        return path.relative_to(cwd).as_posix()
    except ValueError:
        return path.as_posix()


def build_json_report(
    *,
    scanned_files: int,
    flagged_results: Sequence[FileScanResult],
    finding_count: int,
    cwd: Path,
) -> dict:
    serialized_results = []
    for result in sorted(flagged_results, key=lambda item: item.path.as_posix()):
        serialized_findings = []
        for finding in result.findings:
            preview = redact_long_tokens(finding.text.strip())
            if len(preview) > 120:
                preview = f"{preview[:72]} ... {preview[-42:]}"
            serialized_findings.append(
                {
                    "line_number": finding.line_number,
                    "entropy": round(finding.entropy, 6),
                    "token_entropy": round(finding.token_entropy or 0.0, 6),
                    "token_preview": finding.token_preview,
                    "line_preview": preview,
                }
            )
        serialized_results.append(
            {
                "path": _relative_display_path(result.path, cwd),
                "major_type": result.major_type,
                "baseline_entropy": round(result.baseline_entropy, 6),
                "threshold_entropy": round(result.threshold_entropy, 6),
                "findings": serialized_findings,
            }
        )

    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "summary": {
            "scanned_files": scanned_files,
            "flagged_files": len(flagged_results),
            "reported_high_entropy_lines": finding_count,
        },
        "results": serialized_results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cwd = Path.cwd().resolve()

    if args.top_percent < 0 or args.top_percent >= 100:
        print("error: --top-percent must be in [0, 100).", file=sys.stderr)
        return 2
    if args.spike_percent < 0:
        print("error: --spike-percent must be >= 0.", file=sys.stderr)
        return 2
    if args.min_line_length is not None and args.min_line_length < 1:
        print("error: --min-line-length must be >= 1.", file=sys.stderr)
        return 2
    if args.min_token_length < 1:
        print("error: --min-token-length must be >= 1.", file=sys.stderr)
        return 2

    scanned_files = 0
    flagged_results: List[FileScanResult] = []

    for path in iter_files(args.paths, args.exclude):
        scanned_files += 1
        result = scan_file(
            path=path,
            top_percent=args.top_percent,
            spike_percent=args.spike_percent,
            min_line_length=args.min_line_length,
            max_findings_per_file=args.max_findings_per_file,
            min_token_length=args.min_token_length,
        )
        if result is not None:
            flagged_results.append(result)

    finding_count = sum(len(result.findings) for result in flagged_results)

    if args.json_output:
        report = build_json_report(
            scanned_files=scanned_files,
            flagged_results=flagged_results,
            finding_count=finding_count,
            cwd=cwd,
        )
        print(json.dumps(report, indent=2, sort_keys=False))
    else:
        if flagged_results:
            print(render(flagged_results, cwd))
        print(
            (
                f"Scanned {scanned_files} files; "
                f"flagged {len(flagged_results)} files; "
                f"reported {finding_count} high-entropy lines."
            )
        )
    return 1 if finding_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
