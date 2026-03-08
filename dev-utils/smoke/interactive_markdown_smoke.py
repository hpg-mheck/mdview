"""Interactive Markdown smoke harness for mdview.

This utility builds a disposable corpus of random Markdown files and drives
``mdview`` through a pseudo-terminal (PTY). It is intended for exploratory
stress checks that still need to be repeatable, documented, and scriptable.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import fcntl
import hashlib
import json
import os
import pty
import random
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence


MARKDOWN_SUFFIXES = {".md", ".markdown"}
DEFAULT_CANDIDATE_ROOTS = [Path("/usr/share"), Path("/home/mheck/codebase")]
DEFAULT_KEY_CHUNKS = [
    b"j" * 8,
    b"k" * 3,
    b"l" * 16,
    b"h" * 8,
    b"\x1b[6~",  # PageDown
    b"\x1b[5~",  # PageUp
    b"\x1b[F",  # End
    b"\x1b[H",  # Home
    b"q",
]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the smoke harness."""

    parser = argparse.ArgumentParser(
        description=(
            "Run mdview interactive smoke checks across random Markdown files."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--sample-count",
        type=int,
        default=200,
        help="Number of random Markdown files to sample.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducible sampling.",
    )
    parser.add_argument(
        "--candidate-root",
        action="append",
        dest="candidate_roots",
        default=None,
        help="Candidate search root (repeatable).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/tmp"),
        help="Parent directory for disposable output bundles.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Explicit output directory path. Must not already exist.",
    )
    parser.add_argument(
        "--per-file-timeout-seconds",
        type=float,
        default=8.0,
        help="Timeout for each first-pass file execution.",
    )
    parser.add_argument(
        "--retry-timeout-seconds",
        type=float,
        default=10.0,
        help="Timeout for second-pass retry after a failed first pass.",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=24,
        help="PTY viewport row count.",
    )
    parser.add_argument(
        "--cols",
        type=int,
        default=80,
        help="PTY viewport column count.",
    )
    parser.add_argument(
        "--readability-first-every",
        type=int,
        default=10,
        help=(
            "Apply --readability-first-tables every Nth file. Use 0 to disable "
            "the periodic override."
        ),
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=25,
        help="Print progress every N files.",
    )
    parser.add_argument(
        "--python-executable",
        default=sys.executable,
        help="Python interpreter used to launch mdview CLI.",
    )
    parser.add_argument(
        "--mdview-module",
        default="mdview.cli",
        help="Module path used with `python -m` for mdview execution.",
    )
    parser.add_argument(
        "--no-local-pythonpath",
        action="store_true",
        help="Do not prepend this repository's ./src directory to PYTHONPATH.",
    )
    return parser.parse_args(argv)


def _discover_candidates(roots: Sequence[Path]) -> List[Path]:
    """Return Markdown files found under the provided roots."""

    candidates: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for directory, _, files in os.walk(root, onerror=lambda _: None):
            directory_path = Path(directory)
            for name in files:
                suffix = Path(name).suffix.lower()
                if suffix in MARKDOWN_SUFFIXES:
                    candidates.append(directory_path / name)
    return candidates


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Apply deterministic terminal dimensions to the PTY slave endpoint."""

    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def _safe_read(master_fd: int, timeout_seconds: float) -> bytes:
    """Read available PTY bytes without raising on expected close behavior."""

    ready, _, _ = select.select([master_fd], [], [], timeout_seconds)
    if not ready:
        return b""
    try:
        return os.read(master_fd, 65536)
    except OSError:
        return b""


def _terminate_process(proc: subprocess.Popen) -> None:
    """Stop a process group gracefully, then force kill if needed."""

    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.time() + 0.5
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.02)
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return


def _run_interactive_once(
    *,
    sample_path: Path,
    rows: int,
    cols: int,
    timeout_seconds: float,
    command_prefix: Sequence[str],
    local_pythonpath: Optional[Path],
    readability_first_tables: bool,
) -> Dict[str, object]:
    """Run one interactive mdview session and return execution telemetry."""

    started = time.time()
    output_tail = bytearray()
    proc: Optional[subprocess.Popen] = None

    try:
        master_fd, slave_fd = pty.openpty()
    except OSError as error:
        return {
            "returncode": 99,
            "timed_out": False,
            "duration_ms": 0,
            "tail": f"PTY allocation failed: {error}",
        }

    _set_winsize(slave_fd, rows=rows, cols=cols)

    env = os.environ.copy()
    if local_pythonpath is not None:
        existing = env.get("PYTHONPATH", "")
        if existing:
            env["PYTHONPATH"] = f"{local_pythonpath}{os.pathsep}{existing}"
        else:
            env["PYTHONPATH"] = str(local_pythonpath)

    command = list(command_prefix)
    if readability_first_tables:
        command.append("--readability-first-tables")
    command.append(str(sample_path))

    try:
        proc = subprocess.Popen(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            preexec_fn=os.setsid,
            env=env,
        )
    finally:
        os.close(slave_fd)

    try:
        time.sleep(0.08)
        for chunk in DEFAULT_KEY_CHUNKS:
            if proc.poll() is not None:
                break
            os.write(master_fd, chunk)
            read_deadline = time.time() + 0.05
            while time.time() < read_deadline:
                data = _safe_read(master_fd, 0.01)
                if data:
                    output_tail.extend(data)
            time.sleep(0.02)

        while proc.poll() is None and (time.time() - started) < timeout_seconds:
            data = _safe_read(master_fd, 0.05)
            if data:
                output_tail.extend(data)

        timed_out = proc.poll() is None
        if timed_out:
            _terminate_process(proc)
        returncode = proc.wait(timeout=2)
    finally:
        if proc is not None:
            _terminate_process(proc)
            try:
                proc.wait(timeout=1)
            except Exception:
                pass
        while True:
            data = _safe_read(master_fd, 0.0)
            if not data:
                break
            output_tail.extend(data)
        os.close(master_fd)

    return {
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_ms": int((time.time() - started) * 1000),
        "tail": output_tail[-3000:].decode("utf-8", errors="replace"),
    }


def _create_output_dir(args: argparse.Namespace) -> Path:
    """Create and return the disposable output directory."""

    if args.output_dir is not None:
        output_dir = args.output_dir
        output_dir.mkdir(parents=True, exist_ok=False)
        return output_dir

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_root / f"mdview-random-md-smoke-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=False)
    return output_dir


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Execute the smoke workflow and print a concise summary."""

    args = parse_args(argv)
    if args.sample_count <= 0:
        print("sample-count must be positive", file=sys.stderr)
        return 2

    if args.rows <= 0 or args.cols <= 0:
        print("rows and cols must be positive", file=sys.stderr)
        return 2

    roots = (
        [Path(value) for value in args.candidate_roots]
        if args.candidate_roots
        else DEFAULT_CANDIDATE_ROOTS
    )
    candidates = _discover_candidates(roots)
    if len(candidates) < args.sample_count:
        print(
            f"not enough Markdown candidates ({len(candidates)} found, "
            f"{args.sample_count} requested)",
            file=sys.stderr,
        )
        return 2

    # Fail early when PTY support is unavailable in this runtime context.
    try:
        probe_master, probe_slave = pty.openpty()
        os.close(probe_master)
        os.close(probe_slave)
    except OSError as error:
        print(f"PTY support unavailable in this environment: {error}", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    sample_paths = rng.sample(candidates, args.sample_count)

    output_dir = _create_output_dir(args)
    samples_dir = output_dir / "samples"
    samples_dir.mkdir()

    manifest = []
    for index, source in enumerate(sample_paths, start=1):
        digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:10]
        extension = source.suffix.lower() or ".md"
        sample_name = f"{index:03d}-{digest}{extension}"
        sample_path = samples_dir / sample_name
        shutil.copy2(source, sample_path)
        manifest.append(
            {
                "index": index,
                "source": str(source),
                "sample": str(sample_path),
                "size_bytes": source.stat().st_size,
            }
        )

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    local_pythonpath: Optional[Path] = None
    if not args.no_local_pythonpath:
        repository_root = Path(__file__).resolve().parents[2]
        local_pythonpath = repository_root / "src"

    command_prefix = [
        args.python_executable,
        "-m",
        args.mdview_module,
    ]

    results = []
    for position, item in enumerate(manifest, start=1):
        readability_first = (
            args.readability_first_every > 0
            and position % args.readability_first_every == 0
        )
        first = _run_interactive_once(
            sample_path=Path(item["sample"]),
            rows=args.rows,
            cols=args.cols,
            timeout_seconds=args.per_file_timeout_seconds,
            command_prefix=command_prefix,
            local_pythonpath=local_pythonpath,
            readability_first_tables=readability_first,
        )
        entry = {
            "index": item["index"],
            "sample": item["sample"],
            "source": item["source"],
            "size_bytes": item["size_bytes"],
            "readability_first_tables": readability_first,
            "returncode": first["returncode"],
            "timed_out": first["timed_out"],
            "duration_ms": first["duration_ms"],
        }

        failed = bool(first["timed_out"]) or int(first["returncode"]) != 0
        if failed:
            second = _run_interactive_once(
                sample_path=Path(item["sample"]),
                rows=args.rows,
                cols=args.cols,
                timeout_seconds=args.retry_timeout_seconds,
                command_prefix=command_prefix,
                local_pythonpath=local_pythonpath,
                readability_first_tables=readability_first,
            )
            entry.update(
                {
                    "retry_returncode": second["returncode"],
                    "retry_timed_out": second["timed_out"],
                    "retry_duration_ms": second["duration_ms"],
                    "initial_tail": first["tail"],
                    "retry_tail": second["tail"],
                }
            )
        results.append(entry)

        if args.progress_interval > 0 and position % args.progress_interval == 0:
            first_failures = sum(
                1
                for record in results
                if bool(record["timed_out"]) or int(record["returncode"]) != 0
            )
            print(
                f"progress: {position}/{len(manifest)}, "
                f"first-pass failures: {first_failures}"
            )

    first_pass_failures = sum(
        1
        for record in results
        if bool(record["timed_out"]) or int(record["returncode"]) != 0
    )
    persistent_failures = sum(
        1
        for record in results
        if (bool(record["timed_out"]) or int(record["returncode"]) != 0)
        and (
            bool(record.get("retry_timed_out", False))
            or int(record.get("retry_returncode", 0)) != 0
        )
    )
    summary = {
        "sample_count": len(manifest),
        "seed": args.seed,
        "candidate_roots": [str(path) for path in roots],
        "output_dir": str(output_dir),
        "first_pass_failures": first_pass_failures,
        "persistent_failures": persistent_failures,
        "max_duration_ms": max(
            (int(record["duration_ms"]) for record in results), default=0
        ),
        "avg_duration_ms": int(
            sum(int(record["duration_ms"]) for record in results) / max(len(results), 1)
        ),
    }

    (output_dir / "smoke-results.json").write_text(
        json.dumps({"summary": summary, "results": results}, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))
    print(output_dir / "manifest.json")
    print(output_dir / "smoke-results.json")
    return 0 if persistent_failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
