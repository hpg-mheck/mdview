#!/usr/bin/env python3
"""Run repository quality checks with content-hash caching."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


SCHEMA_VERSION = "1.0.0"

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

CHECK_ORDER = [
    "black",
    "ruff",
    "compileall",
    "entropy_check",
    "entropy_tripwire_verify",
    "pytest",
]

CHECK_SCOPE: Dict[str, Dict[str, object]] = {
    "black": {
        "roots": ["src", "tests", "scripts", "dev-utils"],
        "extensions": [".py", ".pyi"],
        "extra_files": ["pyproject.toml"],
    },
    "ruff": {
        "roots": ["src", "tests", "scripts", "dev-utils"],
        "extensions": [".py", ".pyi"],
        "extra_files": ["pyproject.toml"],
    },
    "compileall": {
        "roots": ["src", "tests"],
        "extensions": [".py"],
        "extra_files": [],
    },
    "entropy_check": {
        "roots": ["."],
        "extensions": None,
        "extra_files": [],
    },
    "entropy_tripwire_verify": {
        "roots": ["."],
        "extensions": None,
        "extra_files": [],
    },
    "pytest": {
        "roots": ["src", "tests", "resources", "scripts", "dev-utils"],
        "extensions": None,
        "extra_files": ["pyproject.toml"],
    },
}


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run standard quality checks using per-check content hash cache."
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root (default: current directory).",
    )
    parser.add_argument(
        "--cache-file",
        default=".git/mdview-quality-cache.json",
        help="Cache file path relative to repo root.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cache and rerun all checks.",
    )
    parser.add_argument(
        "--checks",
        nargs="*",
        default=CHECK_ORDER,
        help="Subset of checks to run (default: full ordered set).",
    )
    parser.add_argument(
        "--show-cache",
        action="store_true",
        help="Print cache JSON and exit.",
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


def iter_scope_files(
    repo_root: Path,
    roots: Sequence[str],
    extensions: Sequence[str] | None,
    extra_files: Sequence[str],
) -> List[Path]:
    files: List[Path] = []
    excludes = list(DEFAULT_EXCLUDES)
    extension_set = set(extensions) if extensions is not None else None

    for root_name in roots:
        root = (repo_root / root_name).resolve()
        if not root.exists():
            continue
        if root.is_file():
            rel = root.relative_to(repo_root)
            if not path_is_excluded(rel, excludes):
                if extension_set is None or rel.suffix.lower() in extension_set:
                    files.append(root)
            continue

        for current_root, dirnames, filenames in os.walk(root):
            current_path = Path(current_root)
            dirnames[:] = [
                name
                for name in dirnames
                if not path_is_excluded(
                    (current_path / name).relative_to(repo_root), excludes
                )
            ]
            for filename in filenames:
                candidate = current_path / filename
                rel = candidate.relative_to(repo_root)
                if path_is_excluded(rel, excludes):
                    continue
                if (
                    extension_set is not None
                    and rel.suffix.lower() not in extension_set
                ):
                    continue
                files.append(candidate)

    for extra in extra_files:
        extra_path = (repo_root / extra).resolve()
        if extra_path.exists() and extra_path.is_file():
            files.append(extra_path)

    unique_sorted = sorted(set(files))
    return unique_sorted


def fingerprint_files(
    repo_root: Path, files: Iterable[Path], check_name: str
) -> tuple[str, int]:
    digest = hashlib.sha256()
    digest.update(f"schema:{SCHEMA_VERSION}\ncheck:{check_name}\n".encode("utf-8"))
    count = 0
    for file_path in files:
        rel = file_path.relative_to(repo_root).as_posix()
        content = file_path.read_bytes()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
        count += 1
    return digest.hexdigest(), count


def load_cache(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "checks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": SCHEMA_VERSION, "checks": {}}
    if not isinstance(data, dict):
        return {"schema_version": SCHEMA_VERSION, "checks": {}}
    if data.get("schema_version") != SCHEMA_VERSION:
        return {"schema_version": SCHEMA_VERSION, "checks": {}}
    checks = data.get("checks")
    if not isinstance(checks, dict):
        data["checks"] = {}
    return data


def save_cache(path: Path, data: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {
        "schema_version": SCHEMA_VERSION,
        "checks": data.get("checks", {}),
    }
    path.write_text(
        json.dumps(ordered, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def run_check(repo_root: Path, check_name: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "scripts/run_tool_with_timeout.py", check_name]
    return subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo_root = Path(args.repo_root).resolve()
    cache_path = (repo_root / args.cache_file).resolve()

    cache = load_cache(cache_path)
    checks_cache = cache.setdefault("checks", {})
    if not isinstance(checks_cache, dict):
        checks_cache = {}
        cache["checks"] = checks_cache

    requested_checks = args.checks
    for check_name in requested_checks:
        if check_name not in CHECK_SCOPE:
            print(
                f"[quality-gate] FAIL: unknown check '{check_name}'.", file=sys.stderr
            )
            return 2

    if args.show_cache:
        print(json.dumps(cache, indent=2, sort_keys=False))
        return 0

    for check_name in requested_checks:
        scope = CHECK_SCOPE[check_name]
        files = iter_scope_files(
            repo_root=repo_root,
            roots=scope["roots"],  # type: ignore[index]
            extensions=scope["extensions"],  # type: ignore[index]
            extra_files=scope["extra_files"],  # type: ignore[index]
        )
        fingerprint, file_count = fingerprint_files(repo_root, files, check_name)

        cache_entry = checks_cache.get(check_name)
        if (
            not args.no_cache
            and isinstance(cache_entry, dict)
            and cache_entry.get("fingerprint") == fingerprint
            and cache_entry.get("status") == "pass"
        ):
            print(
                f"[quality-gate] SKIP {check_name}: cache hit "
                f"({file_count} files fingerprinted)."
            )
            continue

        print(
            f"[quality-gate] RUN {check_name}: cache miss "
            f"({file_count} files fingerprinted)."
        )
        result = run_check(repo_root, check_name)
        output = (result.stdout or "") + (result.stderr or "")
        if output:
            print(output.rstrip())

        if result.returncode != 0:
            checks_cache[check_name] = {
                "status": "fail",
                "fingerprint": fingerprint,
                "files_count": file_count,
                "updated_at": now_iso(),
                "last_exit_code": result.returncode,
            }
            save_cache(cache_path, cache)
            print(
                f"[quality-gate] FAIL {check_name}: exit {result.returncode}.",
                file=sys.stderr,
            )
            return result.returncode

        checks_cache[check_name] = {
            "status": "pass",
            "fingerprint": fingerprint,
            "files_count": file_count,
            "updated_at": now_iso(),
            "last_exit_code": 0,
        }
        save_cache(cache_path, cache)

    print("[quality-gate] PASS: all requested checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
