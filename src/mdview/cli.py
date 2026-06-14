"""Command-line interface for mdview.

The CLI stays deliberately explicit because the generated help text, release
artifacts, and tests all depend on stable option behavior. Keep policy
decisions readable here instead of hiding them behind clever abstractions.
"""

import argparse
import codecs
import io
import json
import math
import os
import queue
import selectors
import shutil
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence, TextIO

from mdview import __version__
from mdview.input_formats import DetectedInputFormat, detect_input_format
from mdview.input_feedback import run_test_input_feedback
from mdview.limits import (
    BYTES_PER_MEGABYTE,
    DEFAULT_BOUNDED_INPUT_MEGABYTES,
    DEFAULT_BOUNDED_INPUT_LIMIT_BYTES,
    GEOMETRY_DEFAULT_ABSOLUTE_LIMIT,
    GEOMETRY_DEFAULT_RENDER_LIMIT,
    GEOMETRY_INSANE_ABSOLUTE_LIMIT,
    HUGE_BOUNDED_INPUT_LIMIT_BYTES,
    STDIN_READ_CHUNK_BYTES,
    TEXT_READ_CHUNK_BYTES,
    bounded_input_limit_bytes,
    clamp_geometry_for_render,
    format_byte_limit,
    geometry_absolute_limit,
)
from mdview.prerequisites import (
    detect_prerequisite_issues,
    report_prerequisite_issues,
)
from mdview.rendering import (
    get_fallback_notices,
    is_markdown_file,
    page_text,
    render_to_ansi,
)
from mdview.resize_verifier import ResizeDetectionVerifier


@dataclass(frozen=True)
class _LoadedDocument:
    """Preloaded source and render policy metadata for one input path."""

    path: Path
    content: str
    markdown: bool
    reflow_mode: str


AutomationReplayEvent = tuple[float, str]
_STDIN_IDLE_TIMEOUT_SECONDS = 2.0
_STDIN_MAX_BUFFER_MEGABYTES = float(DEFAULT_BOUNDED_INPUT_MEGABYTES)
_STDIN_SOURCE_LABEL = Path("<stdin>")
_STDIN_BUFFERING_INITIAL_STATUS = "Buffering stdin..."
_STDIN_BUFFERING_COMPLETE_STATUS = "Buffering stdin... complete."
_STDIN_BUFFERING_TIMEOUT_STATUS = "Buffering stdin... giving up after timeout"
_STDIN_BUFFERING_LIMIT_STATUS = "Buffering stdin... failed: exceeds max size limit"


class _StdinBufferLimitExceeded(RuntimeError):
    """Raised when buffered stdin would exceed the configured safety ceiling."""


class _BoundedReadLimitExceeded(RuntimeError):
    """Raised when a bounded text input would exceed the active byte ceiling."""


@dataclass(frozen=True)
class _BufferedStdinReadResult:
    """Buffered stdin text plus the reason buffering stopped."""

    content: str
    received_data: bool
    timed_out: bool


@dataclass(frozen=True)
class _BufferedStdinResult:
    """Buffered stdin payload plus the final startup status line."""

    content: str
    detected_format: DetectedInputFormat
    timed_out: bool
    final_status_line: str


def _non_negative_seconds(value: str) -> float:
    """Return a validated non-negative timeout value in seconds."""

    try:
        seconds = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"invalid timeout seconds value: {value!r}"
        ) from error
    if not math.isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError(
            "automation timeout must be a non-negative finite number"
        )
    return seconds


def _non_negative_stdin_timeout_seconds(value: str) -> float:
    """Return a validated non-negative stdin timeout value in seconds."""

    try:
        seconds = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"invalid timeout seconds value: {value!r}"
        ) from error
    if not math.isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError(
            "stdin timeout must be a non-negative finite number"
        )
    return seconds


def _positive_int(value: str) -> int:
    """Return a validated positive integer option value."""

    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"invalid positive integer value: {value!r}"
        ) from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _positive_megabytes(value: str) -> float:
    """Return a validated positive megabyte limit."""

    try:
        megabytes = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"invalid megabyte value: {value!r}"
        ) from error
    if not math.isfinite(megabytes) or megabytes <= 0:
        raise argparse.ArgumentTypeError(
            "stdin buffer megabytes must be a positive finite number"
        )
    return megabytes


def _stdin_supports_buffered_document(input_stream: TextIO = sys.stdin) -> bool:
    """Return whether ``input_stream`` looks like a real non-TTY document source."""

    if bool(getattr(input_stream, "isatty", lambda: True)()):
        return False

    fileno = getattr(input_stream, "fileno", None)
    if not callable(fileno):
        return False
    try:
        fileno()
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        return False
    return True


def _stdin_buffer_limit_bytes(max_buffer_megabytes: float) -> int:
    """Return the configured stdin ceiling in bytes."""

    return max(1, math.ceil(max_buffer_megabytes * BYTES_PER_MEGABYTE))


def _stdin_buffer_limit_error(max_buffer_bytes: int) -> _StdinBufferLimitExceeded:
    """Return the standardized oversize-stdin error message."""

    configured_limit = max_buffer_bytes / BYTES_PER_MEGABYTE
    return _StdinBufferLimitExceeded(
        "buffered stdin exceeded the configured "
        f"{configured_limit:g} megabyte safety limit. Re-run with "
        "--max-stdin-buffer-megabytes=<override-value-in-megabytes> to allow "
        "a larger stdin document."
    )


def _limit_exceeded_message(
    source_label: str,
    *,
    actual_bytes: Optional[int],
    limit_bytes: int,
    escalation_flag: Optional[str],
) -> str:
    """Return a user-facing bounded-input failure message."""

    actual_detail = ""
    if actual_bytes is not None:
        actual_detail = f" ({format_byte_limit(actual_bytes)})"

    if escalation_flag is not None:
        return (
            f"{source_label}{actual_detail} exceeds the default "
            f"{format_byte_limit(limit_bytes)} safety limit. Re-run with "
            f"{escalation_flag} to allow inputs up to "
            f"{format_byte_limit(HUGE_BOUNDED_INPUT_LIMIT_BYTES)}."
        )
    return (
        f"{source_label}{actual_detail} exceeds the absolute "
        f"{format_byte_limit(limit_bytes)} safety limit."
    )


def _read_text_with_byte_limit(
    path: Path,
    *,
    max_bytes: int,
    escalation_flag: Optional[str],
) -> str:
    """Read UTF-8 text from ``path`` without crossing ``max_bytes``."""

    label = f"input file '{path}'"
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    if size is not None and size > max_bytes:
        raise _BoundedReadLimitExceeded(
            _limit_exceeded_message(
                label,
                actual_bytes=size,
                limit_bytes=max_bytes,
                escalation_flag=escalation_flag,
            )
        )

    chunks: list[bytes] = []
    total_bytes = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(TEXT_READ_CHUNK_BYTES)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise _BoundedReadLimitExceeded(
                    _limit_exceeded_message(
                        label,
                        actual_bytes=total_bytes,
                        limit_bytes=max_bytes,
                        escalation_flag=escalation_flag,
                    )
                )
            chunks.append(chunk)

    return b"".join(chunks).decode("utf-8")


def _validate_viewport_geometry(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    """Reject viewport dimensions beyond the active absolute ceiling."""

    absolute_limit = geometry_absolute_limit(
        allow_insane_geometry=args.allow_insane_geometry
    )
    for attribute, option_name in (
        ("viewport_columns", "--viewport-columns"),
        ("viewport_rows", "--viewport-rows"),
    ):
        value = getattr(args, attribute)
        if value is None or value <= absolute_limit:
            continue
        if args.allow_insane_geometry:
            parser.error(f"{option_name} must be <= {absolute_limit}")
        parser.error(
            f"{option_name} must be <= {absolute_limit} unless "
            "--allow-insane-geometry is used; the absolute limit is "
            f"{GEOMETRY_INSANE_ABSOLUTE_LIMIT}"
        )


def _emit_geometry_cap_notice(args: argparse.Namespace) -> None:
    """Warn when explicit viewport geometry is accepted but render-capped."""

    if args.allow_insane_geometry:
        return
    requested = [
        value
        for value in (args.viewport_columns, args.viewport_rows)
        if value is not None and value > GEOMETRY_DEFAULT_RENDER_LIMIT
    ]
    if not requested:
        return
    print(
        "mdview: requested viewport geometry exceeds the default "
        f"{GEOMETRY_DEFAULT_RENDER_LIMIT}-cell render limit; rendering and "
        "framebuffer captures are capped to that limit per axis. Use "
        "--allow-insane-geometry to render larger geometry explicitly.",
        file=sys.stderr,
    )


def _emit_startup_status_line(
    message: str,
    *,
    output_stream: TextIO = sys.stdout,
    replace_previous: bool = False,
) -> None:
    """Write one buffered-stdin status line to stdout when it is a TTY.

    The pager uses the terminal's alternate screen. Keep the status line on the
    main screen so it becomes visible again after full-screen mode exits.
    """

    if not bool(getattr(output_stream, "isatty", lambda: False)()):
        return

    if replace_previous:
        output_stream.write(f"\x1b[1F\x1b[2K{message}\n")
    else:
        output_stream.write(f"{message}\n")
    output_stream.flush()


def _close_stream_quietly(input_stream: TextIO) -> None:
    """Close one input stream, ignoring cleanup failures."""

    try:
        input_stream.close()
    except (AttributeError, OSError, ValueError):
        return


def _read_stdin_with_thread(
    input_stream: TextIO,
    *,
    idle_timeout_seconds: float,
    max_buffer_bytes: int,
    on_first_chunk: Optional[Callable[[], None]] = None,
) -> _BufferedStdinReadResult:
    """Return buffered stdin text, timing out after one idle interval.

    This path exists for environments where selector-based polling cannot watch
    the incoming stream directly. It preserves the same idle-timeout contract
    as the file-descriptor path below.
    """

    item_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()

    def _reader() -> None:
        try:
            while True:
                chunk = input_stream.read(STDIN_READ_CHUNK_BYTES)
                item_queue.put(("chunk", chunk))
                if chunk == "":
                    return
        except BaseException as error:  # pragma: no cover - defensive bridge
            item_queue.put(("error", error))

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    encoding = getattr(input_stream, "encoding", None) or "utf-8"
    error_mode = getattr(input_stream, "errors", None) or "strict"
    chunks: list[str] = []
    received_data = False
    bytes_read = 0
    while True:
        try:
            kind, payload = item_queue.get(timeout=idle_timeout_seconds)
        except queue.Empty:
            return _BufferedStdinReadResult(
                content="".join(chunks),
                received_data=received_data,
                timed_out=True,
            )

        if kind == "error":
            raise payload  # type: ignore[misc]

        chunk = str(payload)
        if chunk == "":
            return _BufferedStdinReadResult(
                content="".join(chunks),
                received_data=received_data,
                timed_out=False,
            )
        if not received_data:
            received_data = True
            if on_first_chunk is not None:
                on_first_chunk()
        bytes_read += len(chunk.encode(encoding, errors=error_mode))
        if bytes_read > max_buffer_bytes:
            raise _stdin_buffer_limit_error(max_buffer_bytes)
        chunks.append(chunk)


def _read_buffered_stdin_content(
    input_stream: TextIO = sys.stdin,
    *,
    idle_timeout_seconds: float = _STDIN_IDLE_TIMEOUT_SECONDS,
    max_buffer_bytes: int = _stdin_buffer_limit_bytes(_STDIN_MAX_BUFFER_MEGABYTES),
    on_first_chunk: Optional[Callable[[], None]] = None,
) -> _BufferedStdinReadResult:
    """Return buffered stdin text plus whether buffering stopped on timeout."""

    encoding = getattr(input_stream, "encoding", None) or "utf-8"
    error_mode = getattr(input_stream, "errors", None) or "strict"

    try:
        fileno = input_stream.fileno()
        selector = selectors.DefaultSelector()
        selector.register(fileno, selectors.EVENT_READ)
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        return _read_stdin_with_thread(
            input_stream,
            idle_timeout_seconds=idle_timeout_seconds,
            max_buffer_bytes=max_buffer_bytes,
            on_first_chunk=on_first_chunk,
        )

    decoder_factory = codecs.getincrementaldecoder(encoding)
    decoder = decoder_factory(errors=error_mode)
    chunks: list[str] = []
    received_data = False
    bytes_read = 0

    try:
        while True:
            ready = selector.select(idle_timeout_seconds)
            if not ready:
                return _BufferedStdinReadResult(
                    content="".join(chunks) + decoder.decode(b"", final=True),
                    received_data=received_data,
                    timed_out=True,
                )

            raw_chunk = os.read(fileno, STDIN_READ_CHUNK_BYTES)
            if not raw_chunk:
                return _BufferedStdinReadResult(
                    content="".join(chunks) + decoder.decode(b"", final=True),
                    received_data=received_data,
                    timed_out=False,
                )
            bytes_read += len(raw_chunk)
            if bytes_read > max_buffer_bytes:
                raise _stdin_buffer_limit_error(max_buffer_bytes)
            if not received_data:
                received_data = True
                if on_first_chunk is not None:
                    on_first_chunk()
            chunks.append(decoder.decode(raw_chunk))
    finally:
        selector.close()


def _buffer_stdin_document(
    input_stream: TextIO = sys.stdin,
    *,
    output_stream: TextIO = sys.stdout,
    idle_timeout_seconds: float = _STDIN_IDLE_TIMEOUT_SECONDS,
    max_buffer_megabytes: float = _STDIN_MAX_BUFFER_MEGABYTES,
) -> Optional[_BufferedStdinResult]:
    """Buffer one piped stdin document before rendering begins."""

    emitted_initial_status = False

    def _emit_initial_status() -> None:
        nonlocal emitted_initial_status
        if emitted_initial_status:
            return
        emitted_initial_status = True
        _emit_startup_status_line(
            _STDIN_BUFFERING_INITIAL_STATUS,
            output_stream=output_stream,
        )

    try:
        read_result = _read_buffered_stdin_content(
            input_stream,
            idle_timeout_seconds=idle_timeout_seconds,
            max_buffer_bytes=_stdin_buffer_limit_bytes(max_buffer_megabytes),
            on_first_chunk=_emit_initial_status,
        )
    except _StdinBufferLimitExceeded:
        if emitted_initial_status:
            _emit_startup_status_line(
                _STDIN_BUFFERING_LIMIT_STATUS,
                output_stream=output_stream,
                replace_previous=True,
            )
        raise

    if not read_result.received_data:
        if read_result.timed_out:
            _close_stream_quietly(input_stream)
        return None

    if read_result.timed_out:
        _close_stream_quietly(input_stream)
    final_status_line = (
        _STDIN_BUFFERING_TIMEOUT_STATUS
        if read_result.timed_out
        else _STDIN_BUFFERING_COMPLETE_STATUS
    )
    if emitted_initial_status:
        _emit_startup_status_line(
            final_status_line,
            output_stream=output_stream,
            replace_previous=True,
        )
    return _BufferedStdinResult(
        content=read_result.content,
        detected_format=detect_input_format(read_result.content),
        timed_out=read_result.timed_out,
        final_status_line=final_status_line,
    )


def _parse_automation_json_source(
    source: str,
    *,
    max_source_bytes: int = DEFAULT_BOUNDED_INPUT_LIMIT_BYTES,
    escalation_flag: Optional[str] = "--allow-huge-automation-scripts",
) -> list[AutomationReplayEvent]:
    """Return validated automation replay events from file or literal JSON."""

    payload = source
    source_bytes = len(source.encode("utf-8"))
    if source_bytes > max_source_bytes:
        raise ValueError(
            _limit_exceeded_message(
                "automation JSON literal",
                actual_bytes=source_bytes,
                limit_bytes=max_source_bytes,
                escalation_flag=escalation_flag,
            )
        )

    try:
        candidate: Optional[Path] = Path(source).expanduser()
        candidate_exists = candidate.exists()
    except (OSError, ValueError):
        candidate = None
        candidate_exists = False
    # The CLI accepts either a literal JSON string or a path. Prefer the file
    # interpretation when the path exists so automation scripts can pass a
    # filename without additional flag syntax.
    if candidate_exists and candidate is not None:
        if not candidate.is_file():
            raise ValueError(f"automation JSON path is not a file: {candidate}")
        try:
            payload = _read_text_with_byte_limit(
                candidate,
                max_bytes=max_source_bytes,
                escalation_flag=escalation_flag,
            )
        except _BoundedReadLimitExceeded as error:
            raise ValueError(str(error)) from error
        except (OSError, UnicodeDecodeError) as error:
            raise ValueError(
                f"failed to read automation JSON file '{candidate}': {error}"
            ) from error

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid automation JSON: {error.msg}") from error

    if not isinstance(parsed, list):
        raise ValueError("automation JSON must be a top-level array")

    events: list[AutomationReplayEvent] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(
                "automation JSON entry "
                f"{index} must be a two-element array: [delay_seconds, key_spec]"
            )
        delay, key_spec = item
        if isinstance(delay, bool) or not isinstance(delay, (int, float)):
            raise ValueError(f"automation JSON entry {index} delay must be a number")
        delay_seconds = float(delay)
        if not math.isfinite(delay_seconds) or delay_seconds < 0:
            raise ValueError(
                f"automation JSON entry {index} delay must be non-negative and finite"
            )
        if not isinstance(key_spec, str) or not key_spec.strip():
            raise ValueError(
                f"automation JSON entry {index} key spec must be a non-empty string"
            )
        events.append((delay_seconds, key_spec))
    return events


def build_parser() -> argparse.ArgumentParser:
    """Build the mdview argument parser with predictable ``--help`` output."""

    formatter = lambda prog: argparse.ArgumentDefaultsHelpFormatter(  # noqa: E731
        prog,
        max_help_position=28,
        width=78,
    )
    parser = argparse.ArgumentParser(
        prog="mdview",
        description=(
            "Render Markdown or plain text in the terminal with integrated "
            "navigation."
        ),
        formatter_class=formatter,
        add_help=True,
        allow_abbrev=False,
    )
    parser.add_argument(
        "paths",
        type=Path,
        nargs="*",
        help=(
            "Path(s) to Markdown or text files to view. Required unless "
            "--verify-resize-detection or --test-input-feedback is used, "
            "or stdin provides a buffered document."
        ),
    )
    parser.add_argument(
        "--verify-resize-detection",
        action="store_true",
        help=(
            "Guide a manual resize sequence, acknowledging detected events and "
            "reporting pass/fail results."
        ),
    )
    parser.add_argument(
        "--test-input-feedback",
        action="store_true",
        help=(
            "Run a two-stage terminal input diagnostic that compares plain "
            "stdin handling against the prompt_toolkit viewer stack."
        ),
    )
    parser.add_argument(
        "--reflow",
        action="store_true",
        help=(
            "Enable reflow processing. If no explicit mode is supplied, "
            "defaults to --reflow-mode prose."
        ),
    )
    parser.add_argument(
        "--reflow-mode",
        choices=("prose", "all", "none"),
        help=(
            "Select reflow policy mode explicitly. Applies even without " "--reflow."
        ),
    )
    parser.add_argument(
        "--noreflow",
        action="store_true",
        help="Disable reflow in all cases (equivalent to --reflow-mode none).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Report key operational events, including document switches in "
            "multi-document sessions."
        ),
    )
    parser.add_argument(
        "--stdin-timeout-in-seconds",
        metavar="SECONDS",
        type=_non_negative_stdin_timeout_seconds,
        default=_STDIN_IDLE_TIMEOUT_SECONDS,
        help=(
            "Stop waiting for additional stdin bytes after SECONDS have "
            "elapsed with no further input."
        ),
    )
    parser.add_argument(
        "--max-stdin-buffer-megabytes",
        metavar="MEGABYTES",
        type=_positive_megabytes,
        default=_STDIN_MAX_BUFFER_MEGABYTES,
        help=(
            "Refuse buffered stdin documents larger than MEGABYTES unless "
            "the operator explicitly raises the safety ceiling."
        ),
    )
    parser.add_argument(
        "--allow-huge",
        action="store_true",
        help=(
            "Allow file inputs up to "
            f"{format_byte_limit(HUGE_BOUNDED_INPUT_LIMIT_BYTES)} instead of "
            f"the default {DEFAULT_BOUNDED_INPUT_MEGABYTES} MiB ceiling."
        ),
    )
    parser.add_argument(
        "--MIL",
        "--mil",
        dest="mil",
        action="store_true",
        help=(
            "Enable Monkey-in-the-Loop telemetry: emit operator action "
            "events and targeted troubleshooting context."
        ),
    )
    parser.add_argument(
        "--readability-first-tables",
        action="store_true",
        help=(
            "Always use readability-first table layout, even when fit-first "
            "could fit the viewport."
        ),
    )
    parser.add_argument(
        "--no-table-borders",
        action="store_true",
        help=(
            "Suppress outer Markdown table borders and leave whitespace gaps "
            "at the table edges."
        ),
    )
    parser.add_argument(
        "--no-cell-borders",
        action="store_true",
        help=(
            "Suppress internal Markdown table cell borders and leave "
            "whitespace gaps between cells."
        ),
    )
    parser.add_argument(
        "--automation-timeout",
        metavar="SECONDS",
        type=_non_negative_seconds,
        help=(
            "Inject synthetic quit after the given viewer runtime for "
            "automation runs."
        ),
    )
    parser.add_argument(
        "--automation-timeout-screenshot",
        metavar="BASENAME",
        type=Path,
        help=(
            "Write timeout-exit framebuffer artifacts using BASENAME, "
            "producing BASENAME.txt and BASENAME.attrs.json. Defaults to "
            "./mdview-automation-timeout-framebuffer when "
            "--automation-timeout is set."
        ),
    )
    parser.add_argument(
        "--screen-dump-dir",
        metavar="DIRECTORY",
        type=Path,
        default=Path("."),
        help=(
            "Directory for manual ! framebuffer captures in the interactive "
            "pager. Defaults to the current working directory."
        ),
    )
    parser.add_argument(
        "--viewport-columns",
        metavar="COLUMNS",
        type=_positive_int,
        help="Override detected viewport width with a synthetic value.",
    )
    parser.add_argument(
        "--viewport-rows",
        metavar="ROWS",
        type=_positive_int,
        help="Override detected viewport height with a synthetic value.",
    )
    parser.add_argument(
        "--allow-insane-geometry",
        action="store_true",
        help=(
            "Render viewport geometry above "
            f"{GEOMETRY_DEFAULT_RENDER_LIMIT} cells per axis. Without this "
            f"flag, values up to {GEOMETRY_DEFAULT_ABSOLUTE_LIMIT} are "
            f"accepted but only the first {GEOMETRY_DEFAULT_RENDER_LIMIT} "
            "cells per axis are rendered. With this flag, the absolute limit "
            f"is {GEOMETRY_INSANE_ABSOLUTE_LIMIT} cells per axis."
        ),
    )
    parser.add_argument(
        "--automation-json",
        metavar="SOURCE",
        help=(
            "Replay key events from JSON SOURCE (file path or literal JSON "
            "string) as [[delay_seconds, key_spec], ...]."
        ),
    )
    parser.add_argument(
        "--allow-huge-automation-scripts",
        action="store_true",
        help=(
            "Allow automation JSON sources up to "
            f"{format_byte_limit(HUGE_BOUNDED_INPUT_LIMIT_BYTES)} instead of "
            f"the default {DEFAULT_BOUNDED_INPUT_MEGABYTES} MiB ceiling."
        ),
    )
    parser.add_argument(
        "--redraw-check-digit",
        action="store_true",
        help=(
            "Overlay a center-screen digit that advances from 0 to 9 on each "
            "interactive pager redraw."
        ),
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"mdview {__version__}",
        help="Show the mdview version and exit.",
    )
    return parser


def format_help() -> str:
    """Return the formatted ``--help`` text for reuse in documentation."""

    return build_parser().format_help()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument list override for testing.

    Returns:
        A populated :class:`argparse.Namespace` instance.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_viewport_geometry(parser, args)
    return args


def _emit_fallback_notices() -> None:
    """Print fallback notices, if any, to standard error before exiting."""

    notices = get_fallback_notices()
    if not notices:
        return

    print("mdview: fallback notices:", file=sys.stderr)
    for notice in notices:
        print(f"  - {notice}", file=sys.stderr)


def _emit_log(message: str) -> None:
    """Write a single status line to standard error."""

    print(message, file=sys.stderr)


def _initial_viewport_width(
    *,
    viewport_columns: Optional[int],
    allow_insane_geometry: bool,
) -> Optional[int]:
    """Return the startup render width for interactive terminal sessions."""

    if viewport_columns is not None:
        return clamp_geometry_for_render(
            viewport_columns,
            allow_insane_geometry=allow_insane_geometry,
        )
    if not sys.stdout.isatty():
        return None
    try:
        columns = shutil.get_terminal_size().columns
    except (OSError, ValueError):
        return None
    if columns <= 0:
        return None
    return clamp_geometry_for_render(
        columns,
        allow_insane_geometry=allow_insane_geometry,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the ``mdview`` CLI."""

    report_prerequisite_issues(detect_prerequisite_issues())
    args = parse_args(argv)
    exit_code = 0
    _emit_geometry_cap_notice(args)

    if args.verify_resize_detection and args.test_input_feedback:
        print(
            "mdview: --verify-resize-detection and --test-input-feedback "
            "cannot be used together",
            file=sys.stderr,
        )
        _emit_fallback_notices()
        return 2

    if args.verify_resize_detection:
        verifier = ResizeDetectionVerifier()
        report = verifier.run()
        _emit_fallback_notices()
        return 0 if report.overall_passed else 1

    if args.test_input_feedback:
        if args.paths:
            print(
                "mdview: --test-input-feedback does not accept document paths",
                file=sys.stderr,
            )
            _emit_fallback_notices()
            return 2
        exit_code = run_test_input_feedback()
        _emit_fallback_notices()
        return exit_code

    paths = list(args.paths)
    buffered_stdin: Optional[_BufferedStdinResult] = None
    if not paths and _stdin_supports_buffered_document():
        try:
            buffered_stdin = _buffer_stdin_document(
                idle_timeout_seconds=args.stdin_timeout_in_seconds,
                max_buffer_megabytes=args.max_stdin_buffer_megabytes,
            )
        except (_StdinBufferLimitExceeded, OSError, UnicodeDecodeError) as error:
            print(f"mdview: failed to read stdin: {error}", file=sys.stderr)
            _emit_fallback_notices()
            return 3

    if not paths and buffered_stdin is None:
        print(
            "mdview: at least one path or buffered stdin input is required unless "
            "--verify-resize-detection or --test-input-feedback is used",
            file=sys.stderr,
        )
        _emit_fallback_notices()
        return 2

    if args.automation_timeout_screenshot and args.automation_timeout is None:
        print(
            "mdview: --automation-timeout-screenshot requires " "--automation-timeout",
            file=sys.stderr,
        )
        _emit_fallback_notices()
        return 2
    if args.screen_dump_dir.exists() and not args.screen_dump_dir.is_dir():
        print(
            "mdview: --screen-dump-dir must name a directory",
            file=sys.stderr,
        )
        _emit_fallback_notices()
        return 2

    automation_replay: Optional[list[AutomationReplayEvent]] = None
    if args.automation_json is not None:
        automation_limit = bounded_input_limit_bytes(
            allow_huge=args.allow_huge_automation_scripts
        )
        automation_escalation_flag = (
            None
            if args.allow_huge_automation_scripts
            else "--allow-huge-automation-scripts"
        )
        try:
            automation_replay = _parse_automation_json_source(
                args.automation_json,
                max_source_bytes=automation_limit,
                escalation_flag=automation_escalation_flag,
            )
        except ValueError as error:
            print(f"mdview: {error}", file=sys.stderr)
            _emit_fallback_notices()
            return 2

    loaded_documents: list[_LoadedDocument] = []
    prefer_tty_input = buffered_stdin is not None
    file_input_limit = bounded_input_limit_bytes(allow_huge=args.allow_huge)
    file_escalation_flag = None if args.allow_huge else "--allow-huge"
    if buffered_stdin is not None:
        stdin_reflow_mode = resolve_reflow_mode(
            markdown=buffered_stdin.detected_format.markdown,
            reflow=args.reflow,
            reflow_mode=args.reflow_mode,
            noreflow=args.noreflow,
        )
        loaded_documents.append(
            _LoadedDocument(
                path=_STDIN_SOURCE_LABEL,
                content=buffered_stdin.content,
                markdown=buffered_stdin.detected_format.markdown,
                reflow_mode=stdin_reflow_mode,
            )
        )

    # Preload all inputs before starting the pager. This keeps document
    # switching deterministic and avoids surprising filesystem I/O once the
    # interactive session is already live.
    for path in paths:
        if not path.exists() or not path.is_file():
            print(
                f"mdview: path does not exist or is not a file: {path}",
                file=sys.stderr,
            )
            exit_code = 2
            _emit_fallback_notices()
            return exit_code

        try:
            content = _read_text_with_byte_limit(
                path,
                max_bytes=file_input_limit,
                escalation_flag=file_escalation_flag,
            )
        except (_BoundedReadLimitExceeded, OSError, UnicodeDecodeError) as error:
            print(f"mdview: failed to read '{path}': {error}", file=sys.stderr)
            exit_code = 3
            _emit_fallback_notices()
            return exit_code

        markdown = is_markdown_file(path)
        reflow_mode = resolve_reflow_mode(
            markdown=markdown,
            reflow=args.reflow,
            reflow_mode=args.reflow_mode,
            noreflow=args.noreflow,
        )
        loaded_documents.append(
            _LoadedDocument(
                path=path,
                content=content,
                markdown=markdown,
                reflow_mode=reflow_mode,
            )
        )

    current_index = 0

    def _render_document(index: int, width: Optional[int] = None) -> str:
        # Rendering stays callback-driven so the pager can request a width-
        # sensitive rerender without needing to understand file I/O or policy.
        document = loaded_documents[index]
        return render_to_ansi(
            document.content,
            markdown=document.markdown,
            width=width,
            reflow_mode=document.reflow_mode,
            readability_first_tables=args.readability_first_tables,
            table_borders=not args.no_table_borders,
            cell_borders=not args.no_cell_borders,
        )

    initial_width = _initial_viewport_width(
        viewport_columns=args.viewport_columns,
        allow_insane_geometry=args.allow_insane_geometry,
    )
    ansi_text = _render_document(current_index, width=initial_width)

    def _render_on_resize(width: int) -> str:
        # Reuse the same document-selection logic during resize so first-frame
        # rendering and resize-driven rendering stay aligned.
        return _render_document(current_index, width=width)

    def _switch_document(delta: int, width: Optional[int]) -> Optional[str]:
        nonlocal current_index
        target_index = current_index + delta
        if target_index < 0 or target_index >= len(loaded_documents):
            return None
        current_index = target_index
        active_path = loaded_documents[current_index].path
        if args.verbose:
            _emit_log(
                "mdview: switched to "
                f"[{current_index + 1}/{len(loaded_documents)}] {active_path}"
            )
        return _render_document(current_index, width=width)

    def _ui_event_logger(action: str, context: dict[str, object]) -> None:
        # MIL output intentionally keeps one narrow choke point so future
        # instrumentation changes do not need to chase logging calls across the
        # interactive stack.
        if not args.mil:
            return
        if args.verbose:
            ordered = ", ".join(
                f"{key}={value}" for key, value in sorted(context.items())
            )
            suffix = f" ({ordered})" if ordered else ""
            _emit_log(f"mdview[MIL]: {action}{suffix}")
            return
        _emit_log(f"mdview[MIL]: {action}")

    timeout_screenshot_basename = args.automation_timeout_screenshot
    if args.automation_timeout is not None and timeout_screenshot_basename is None:
        # Keep the implicit basename here, not in the pager, so help text,
        # tests, and runtime behavior all describe the same default.
        timeout_screenshot_basename = Path("mdview-automation-timeout-framebuffer")

    try:
        page_text(
            ansi_text,
            render_on_resize=_render_on_resize,
            switch_document=_switch_document if len(loaded_documents) > 1 else None,
            ui_event_logger=_ui_event_logger if args.mil else None,
            prefer_tty_input=prefer_tty_input,
            document_count=len(loaded_documents),
            current_document_index=lambda: current_index,
            automation_timeout=args.automation_timeout,
            automation_timeout_screenshot_basename=timeout_screenshot_basename,
            screen_dump_dir=args.screen_dump_dir,
            viewport_columns=args.viewport_columns,
            viewport_rows=args.viewport_rows,
            allow_insane_geometry=args.allow_insane_geometry,
            automation_replay=automation_replay,
            redraw_check_digit=args.redraw_check_digit,
        )
    except RuntimeError as error:
        print(f"mdview: pager error: {error}", file=sys.stderr)
        exit_code = 4
    _emit_fallback_notices()
    return exit_code


def resolve_reflow_mode(
    *,
    markdown: bool,
    reflow: bool,
    reflow_mode: Optional[str],
    noreflow: bool,
) -> str:
    """Resolve the effective reflow mode from CLI flags and source defaults."""

    if noreflow:
        return "none"
    if reflow_mode is not None:
        return reflow_mode
    if reflow:
        return "prose"
    if markdown:
        return "prose"
    return "none"


if __name__ == "__main__":
    sys.exit(main())
