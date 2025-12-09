"""Core rendering and paging utilities for mdview.

The module keeps the Markdown-to-ANSI pipeline compact while offering a minimal
extension point for overriding the pager command. All public functions are
covered by unit tests to ensure reliable behavior.
"""

import importlib.util
import os
import shlex
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Type


class _PlainMarkdown:
    """Minimal stub to allow rendering without Rich installed."""

    def __init__(self, text: str, code_theme: Optional[str] = None) -> None:
        self.text = text
        self.code_theme = code_theme


class _PlainConsole:
    """Simplified Console replacement used only when Rich is missing."""

    def __init__(self, record: bool = False) -> None:
        self._buffer: List[str] = []

    def print(self, content: object) -> None:
        text = getattr(content, "text", content)
        self._buffer.append(str(text))

    def export_text(self, styles: bool = True) -> str:
        return "\n".join(self._buffer)


def _select_rendering_backend() -> Tuple[Type[object], Type[object], bool]:
    """Determine whether Rich is available and return rendering primitives.

    Returns:
        A tuple of (Console class, Markdown class, has_rich flag). The
        returned classes always satisfy the minimal interface used by
        ``render_to_ansi`` regardless of whether Rich is installed.
    """

    if importlib.util.find_spec("rich") is None:
        return _PlainConsole, _PlainMarkdown, False

    from rich.console import Console  # type: ignore
    from rich.markdown import Markdown  # type: ignore

    return Console, Markdown, True


Console, Markdown, HAS_RICH = _select_rendering_backend()


# Type alias for pager callables used in tests and potential future hooks.
Pager = Callable[[str], None]


def is_markdown_file(path: Path) -> bool:
    """Return ``True`` when the path looks like a Markdown document.

    A simple suffix check keeps the rule transparent and predictable. Markdown
    detection is intentionally conservative: only ``.md`` and ``.markdown``
    files are treated as Markdown; everything else is emitted as plain text.
    """

    suffix = path.suffix.lower()
    return suffix in {".md", ".markdown"}


def read_text(path: Path) -> str:
    """Read the file content as UTF-8 text.

    Args:
        path: Path to the file on disk.

    Returns:
        The file content as a string.

    Raises:
        FileNotFoundError: If the path does not exist.
        PermissionError: If the process lacks permission to read the file.
        OSError: For other I/O related errors.
    """

    return path.read_text(encoding="utf-8")


def render_to_ansi(content: str, markdown: bool) -> str:
    """Render the given content to ANSI-decorated text.

    When ``markdown`` is true, the content is parsed through ``rich``'s
    ``Markdown`` renderer; otherwise the text is printed verbatim. ``Console``
    is run in record mode so that the emitted ANSI escape sequences can be
    exported for paging. When Rich is unavailable, the fallback console and
    markdown stubs record plain text output without styling.

    Args:
        content: The document content to render.
        markdown: Whether to process the content as Markdown.

    Returns:
        A string containing ANSI escape sequences suitable for paging.
    """

    console = Console(record=True)
    if markdown:
        console.print(Markdown(content, code_theme="ansi_dark"))
    else:
        console.print(content)
    return console.export_text(styles=True)


def page_text(
    text: str,
    pager: Optional[Pager] = None,
    pager_command: Optional[str] = None,
) -> None:
    """Send text to a pager for interactive navigation.

    Args:
        text: Rendered ANSI text to display.
        pager: Optional callable to handle paging (primarily for testing).
        pager_command: Optional shell-style pager command to execute instead of
            the default ``pydoc.pager`` / ``less`` combination.

    Raises:
        RuntimeError: If the custom pager command fails to start or exits with
            a non-zero status.
    """

    if pager:
        pager(text)
        return

    if pager_command:
        _pipe_to_command(text, pager_command)
        return

    # Default: rely on ``pydoc.pager`` which prefers ``less`` when available.
    # The LESS environment variable ensures ANSI escape sequences are retained.
    os.environ.setdefault("LESS", "-R")
    import pydoc  # Local import to keep import cost low until needed

    pydoc.pager(text)


def _pipe_to_command(text: str, command: str) -> None:
    """Send text to an external pager command.

    Args:
        text: Rendered ANSI text to display.
        command: Shell-style command string, e.g., ``"less -R"``.

    Raises:
        RuntimeError: If the command cannot be executed or returns a non-zero
            exit status.
    """

    args = shlex.split(command)
    try:
        with subprocess.Popen(args, stdin=subprocess.PIPE) as process:
            assert process.stdin is not None  # For type checkers
            process.stdin.write(text.encode("utf-8"))
            process.stdin.close()
            return_code = process.wait()
    except OSError as error:
        raise RuntimeError(
            f"Failed to execute pager command '{command}': {error}"
        ) from error

    if return_code != 0:
        raise RuntimeError(
            f"Pager command '{command}' exited with status {return_code}"
        )
