"""Command-line interface for mdview.

The CLI stays deliberately explicit because the generated help text, release
artifacts, and tests all depend on stable option behavior. Keep policy
decisions readable here instead of hiding them behind clever abstractions.
"""

import argparse
import json
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from mdview import __version__
from mdview.input_feedback import run_test_input_feedback
from mdview.prerequisites import (
    detect_prerequisite_issues,
    report_prerequisite_issues,
)
from mdview.rendering import (
    get_fallback_notices,
    is_markdown_file,
    page_text,
    read_text,
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


def _parse_automation_json_source(source: str) -> list[AutomationReplayEvent]:
    """Return validated automation replay events from file or literal JSON."""

    payload = source
    candidate = Path(source).expanduser()
    # The CLI accepts either a literal JSON string or a path. Prefer the file
    # interpretation when the path exists so automation scripts can pass a
    # filename without additional flag syntax.
    if candidate.exists():
        if not candidate.is_file():
            raise ValueError(f"automation JSON path is not a file: {candidate}")
        try:
            payload = candidate.read_text(encoding="utf-8")
        except OSError as error:
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
        description="Render Markdown in the terminal with integrated navigation.",
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
            "--verify-resize-detection or --test-input-feedback is used."
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
        "--automation-json",
        metavar="SOURCE",
        help=(
            "Replay key events from JSON SOURCE (file path or literal JSON "
            "string) as [[delay_seconds, key_spec], ...]."
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
    return parser.parse_args(argv)


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


def _initial_viewport_width(*, viewport_columns: Optional[int]) -> Optional[int]:
    """Return the startup render width for interactive terminal sessions."""

    if viewport_columns is not None:
        return viewport_columns
    if not sys.stdout.isatty():
        return None
    try:
        columns = shutil.get_terminal_size().columns
    except (OSError, ValueError):
        return None
    return columns if columns > 0 else None


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the ``mdview`` CLI."""

    report_prerequisite_issues(detect_prerequisite_issues())
    args = parse_args(argv)
    exit_code = 0

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
    if not paths:
        print(
            "mdview: at least one path is required unless "
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

    automation_replay: Optional[list[AutomationReplayEvent]] = None
    if args.automation_json is not None:
        try:
            automation_replay = _parse_automation_json_source(args.automation_json)
        except ValueError as error:
            print(f"mdview: {error}", file=sys.stderr)
            _emit_fallback_notices()
            return 2

    loaded_documents: list[_LoadedDocument] = []
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
            content = read_text(path)
        except (OSError, UnicodeDecodeError) as error:
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
        )

    initial_width = _initial_viewport_width(viewport_columns=args.viewport_columns)
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
            document_count=len(loaded_documents),
            current_document_index=lambda: current_index,
            automation_timeout=args.automation_timeout,
            automation_timeout_screenshot_basename=timeout_screenshot_basename,
            viewport_columns=args.viewport_columns,
            viewport_rows=args.viewport_rows,
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
