"""Command-line interface for mdview."""

import argparse
import sys
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


def build_parser() -> argparse.ArgumentParser:
    """Build the mdview argument parser with predictable ``--help`` output."""

    formatter = lambda prog: argparse.ArgumentDefaultsHelpFormatter(  # noqa: E731
        prog,
        max_help_position=28,
        width=78,
    )
    parser = argparse.ArgumentParser(
        prog="mdview",
        description="Render Markdown in the terminal with less-like navigation.",
        formatter_class=formatter,
        add_help=True,
        allow_abbrev=False,
    )
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        help=(
            "Path to a Markdown or text file to view. Required unless "
            "--verify-resize-detection is used."
        ),
    )
    parser.add_argument(
        "--pager",
        dest="pager_command",
        metavar="COMMAND",
        help=(
            "Optional pager command to override the default less/pydoc pager "
            "(e.g., 'less -R')."
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
            "Select reflow policy mode explicitly. Applies even without "
            "--reflow."
        ),
    )
    parser.add_argument(
        "--noreflow",
        action="store_true",
        help="Disable reflow in all cases (equivalent to --reflow-mode none).",
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

    path: Optional[Path] = args.path
    if path is None:
        print(
            "mdview: path is required unless --verify-resize-detection is used",
            file=sys.stderr,
        )
        _emit_fallback_notices()
        return 2
    if not path.exists() or not path.is_file():
        print(f"mdview: path does not exist or is not a file: {path}", file=sys.stderr)
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

    is_markdown = is_markdown_file(path)
    active_reflow_mode = resolve_reflow_mode(
        markdown=is_markdown,
        reflow=args.reflow,
        reflow_mode=args.reflow_mode,
        noreflow=args.noreflow,
    )
    ansi_text = render_to_ansi(
        content,
        markdown=is_markdown,
        reflow_mode=active_reflow_mode,
    )

    try:
        page_text(
            ansi_text,
            pager_command=args.pager_command,
            render_on_resize=lambda width: render_to_ansi(
                content,
                markdown=is_markdown,
                width=width,
                reflow_mode=active_reflow_mode,
            ),
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
