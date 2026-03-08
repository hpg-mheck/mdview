"""Command-line interface for mdview."""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from mdview import __version__
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
            "--verify-resize-detection is used."
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the ``mdview`` CLI."""

    report_prerequisite_issues(detect_prerequisite_issues())
    args = parse_args(argv)
    exit_code = 0

    if args.verify_resize_detection:
        verifier = ResizeDetectionVerifier()
        report = verifier.run()
        _emit_fallback_notices()
        return 0 if report.overall_passed else 1

    paths = list(args.paths)
    if not paths:
        print(
            "mdview: at least one path is required unless "
            "--verify-resize-detection is used",
            file=sys.stderr,
        )
        _emit_fallback_notices()
        return 2

    loaded_documents: list[_LoadedDocument] = []
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
        document = loaded_documents[index]
        return render_to_ansi(
            document.content,
            markdown=document.markdown,
            width=width,
            reflow_mode=document.reflow_mode,
            readability_first_tables=args.readability_first_tables,
        )

    ansi_text = _render_document(current_index, width=None)

    def _render_on_resize(width: int) -> str:
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

    try:
        page_text(
            ansi_text,
            render_on_resize=_render_on_resize,
            switch_document=_switch_document if len(loaded_documents) > 1 else None,
            ui_event_logger=_ui_event_logger if args.mil else None,
            document_count=len(loaded_documents),
            current_document_index=lambda: current_index,
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
