"""Command-line interface for mdview."""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from mdview import __version__
from mdview.rendering import is_markdown_file, page_text, read_text, render_to_ansi


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument list override for testing.

    Returns:
        A populated :class:`argparse.Namespace` instance.
    """

    parser = argparse.ArgumentParser(
        prog="mdview",
        description="Render Markdown in the terminal with less-like navigation.",
    )
    parser.add_argument(
        "path", type=Path, help="Path to a Markdown or text file to view."
    )
    parser.add_argument(
        "--pager",
        dest="pager_command",
        help="Optional pager command to override the default less/pydoc pager (e.g., 'less -R').",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mdview {__version__}",
        help="Show the mdview version and exit.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the ``mdview`` CLI."""

    args = parse_args(argv)
    path: Path = args.path
    if not path.exists() or not path.is_file():
        print(f"mdview: path does not exist or is not a file: {path}", file=sys.stderr)
        return 2

    try:
        content = read_text(path)
    except (OSError, UnicodeDecodeError) as error:
        print(f"mdview: failed to read '{path}': {error}", file=sys.stderr)
        return 3

    ansi_text = render_to_ansi(content, markdown=is_markdown_file(path))

    try:
        page_text(ansi_text, pager_command=args.pager_command)
    except RuntimeError as error:
        print(f"mdview: pager error: {error}", file=sys.stderr)
        return 4

    return 0


if __name__ == "__main__":
    sys.exit(main())
