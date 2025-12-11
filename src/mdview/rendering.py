"""Core rendering and paging utilities for mdview.

The module keeps the Markdown-to-ANSI pipeline compact while offering a minimal
extension point for overriding the pager command. All public functions are
covered by unit tests to ensure reliable behavior.
"""

import importlib.util
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence, Tuple, Type

from mdview.hyperlinks import (
    Hyperlink,
    HyperlinkNavigator,
    normalize_hyperlinks,
)

if TYPE_CHECKING:  # pragma: no cover - imported for static analysis only
    from prompt_toolkit.layout.containers import Window


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


_FALLBACK_NOTICES: List[str] = []
_EMPTY_HEADING_SENTINEL = "MDVIEWEMPTYHEADING"
_FORCED_BREAK_SENTINEL = "MDVIEWHEADINGBREAK"
_ANSI_ESCAPE_PATTERN = r"\x1b\[[0-?]*[ -/]*[@-~]"


def _add_fallback_notice(message: str) -> None:
    """Record a fallback notice without duplicating prior entries."""

    if message not in _FALLBACK_NOTICES:
        _FALLBACK_NOTICES.append(message)


def _split_table_row(line: str) -> List[str]:
    """Return a list of cell contents for a pipe-delimited table row."""

    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _alignment_from_divider(cell: str) -> str:
    """Map a divider cell to a text alignment rule."""

    trimmed = cell.strip()
    left = trimmed.startswith(":")
    right = trimmed.endswith(":")
    if left and right:
        return "center"
    if right:
        return "right"
    return "left"


def _is_divider_row(line: str) -> bool:
    """Return True when the line represents a Markdown table divider row."""

    cells = _split_table_row(line)
    if not cells:
        return False

    for cell in cells:
        trimmed = cell.strip()
        if not trimmed:
            return False
        if set(trimmed) - {"-", ":"}:
            return False
        if trimmed.count("-") < 3:
            return False
    return True


def _format_table_block(lines: Sequence[str], start: int) -> Tuple[List[str], int]:
    """Return formatted table rows and the index after the table block.

    Args:
        lines: Full document lines.
        start: Index pointing to the header row.

    Returns:
        A tuple containing the formatted table lines and the index after the
        final table row.
    """

    if start + 1 >= len(lines):
        return [], start

    header_cells = _split_table_row(lines[start])
    divider_line = lines[start + 1]
    if not _is_divider_row(divider_line):
        return [], start

    divider_cells = _split_table_row(divider_line)
    alignments = [_alignment_from_divider(cell) for cell in divider_cells]

    rows: List[List[str]] = [header_cells]
    index = start + 2
    while index < len(lines):
        candidate = lines[index]
        if not candidate.strip():
            break
        if "|" not in candidate:
            break
        row_cells = _split_table_row(candidate)
        if len(row_cells) < 2:
            break
        rows.append(row_cells)
        index += 1

    column_count = max(len(row) for row in rows + [alignments])
    widths: List[int] = []
    for column in range(column_count):
        width = 0
        for row in rows:
            if column < len(row):
                width = max(width, len(row[column].strip()))
        if column < len(divider_cells):
            width = max(width, len(divider_cells[column].strip(" :")))
        widths.append(width)

    def _format_row(row: Sequence[str]) -> str:
        padded_cells: List[str] = []
        for column, width in enumerate(widths):
            text = row[column].strip() if column < len(row) else ""
            alignment = alignments[column] if column < len(alignments) else "left"
            if alignment == "center":
                padded = text.center(width)
            elif alignment == "right":
                padded = text.rjust(width)
            else:
                padded = text.ljust(width)
            padded_cells.append(padded)
        return "| " + " | ".join(padded_cells) + " |"

    def _format_divider() -> str:
        divider_cells: List[str] = []
        for column, width in enumerate(widths):
            alignment = alignments[column] if column < len(alignments) else "left"
            dash_width = max(width, 3)
            if alignment == "center":
                cell = ":" + "-" * max(dash_width - 2, 1) + ":"
            elif alignment == "right":
                cell = "-" * max(dash_width - 1, 2) + ":"
            else:
                cell = ":" + "-" * max(dash_width - 1, 2)
            divider_cells.append(cell)
        return "| " + " | ".join(divider_cells) + " |"

    formatted_lines: List[str] = [_format_row(rows[0]), _format_divider()]
    for row in rows[1:]:
        formatted_lines.append(_format_row(row))

    return formatted_lines, index


def _format_pipe_tables(text: str) -> str:
    """Return content with pipe tables aligned for plain-text readability."""

    lines = text.splitlines()
    output: List[str] = []
    index = 0
    in_fence = False
    fence_marker: Optional[str] = None

    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif fence_marker and stripped.startswith(fence_marker):
                in_fence = False
                fence_marker = None
            output.append(line)
            index += 1
            continue

        if in_fence:
            output.append(line)
            index += 1
            continue

        if "|" in line and index + 1 < len(lines) and _is_divider_row(lines[index + 1]):
            formatted, next_index = _format_table_block(lines, index)
            if formatted:
                output.extend(formatted)
                index = next_index
                continue

        output.append(line)
        index += 1

    return "\n".join(output)


def _normalize_heading_input(text: str, has_rich: bool) -> str:
    """Return content adjusted to honor heading-specific constraints."""

    normalized: List[str] = []
    for line in text.splitlines():
        stripped = line.lstrip(" \t")
        if not stripped:
            normalized.append(line)
            continue

        if stripped.startswith("#"):
            heading_body = stripped.lstrip("#").strip()
            if not heading_body:
                if has_rich:
                    normalized.append(_EMPTY_HEADING_SENTINEL)
                else:
                    normalized.append("")
                continue

            if has_rich and len(stripped) != len(line):
                normalized.append(
                    f"{line[: len(line) - len(stripped)]}\\{stripped}"
                    f" {_FORCED_BREAK_SENTINEL}"
                )
                continue

        normalized.append(line)

    return "\n".join(normalized)


def _normalize_bulleted_lists(text: str, has_rich: bool) -> str:
    """Ensure bulleted list blocks remain visually separated."""

    lines = text.splitlines()
    output: List[str] = []
    in_list = False
    current_marker: Optional[str] = None

    def _append_break() -> None:
        if has_rich:
            output.append("")
            output.extend([_FORCED_BREAK_SENTINEL, _FORCED_BREAK_SENTINEL])
        else:
            output.append("")

    for line in lines:
        stripped = line.lstrip()
        is_bullet = stripped.startswith("- ") or stripped.startswith("* ")
        marker = stripped[:1] if is_bullet else None

        if is_bullet:
            if not in_list and output and output[-1].strip():
                _append_break()
            elif in_list and marker != current_marker:
                _append_break()

            output.append(line)
            in_list = True
            current_marker = marker
            continue

        if in_list:
            if not line.strip():
                _append_break()
                in_list = False
                current_marker = None
                continue

            if output and output[-1].strip() and line.strip():
                _append_break()
            in_list = False
            current_marker = None

        output.append(line)

    return "\n".join(output)


def _select_rendering_backend() -> Tuple[Type[object], Type[object], bool]:
    """Determine whether Rich is available and return rendering primitives.

    Returns:
        A tuple of (Console class, Markdown class, has_rich flag). The
        returned classes always satisfy the minimal interface used by
        ``render_to_ansi`` regardless of whether Rich is installed.
    """

    if importlib.util.find_spec("rich") is None:
        _FALLBACK_NOTICES.append(
            "Rich not available: using plain-text rendering. Install 'rich' for "
            "styled output."
        )
        return _PlainConsole, _PlainMarkdown, False

    from rich.console import Console  # type: ignore
    from rich.markdown import Markdown  # type: ignore

    return Console, Markdown, True


Console, Markdown, HAS_RICH = _select_rendering_backend()


# Type alias for pager callables used in tests and potential future hooks.
Pager = Callable[[str], None]


def get_fallback_notices() -> List[str]:
    """Return human-readable notices describing active fallback behavior."""

    return list(_FALLBACK_NOTICES)


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
        trailing_newline = content.endswith(("\n", "\r\n"))
        normalized = _normalize_heading_input(content, HAS_RICH)
        normalized = _normalize_bulleted_lists(normalized, HAS_RICH)
        formatted = _format_pipe_tables(normalized)
        if trailing_newline:
            formatted += "\n"
        console.print(Markdown(formatted, code_theme="ansi_dark"))
    else:
        console.print(content)

    rendered = console.export_text(styles=True)
    if markdown and HAS_RICH:
        empty_pattern = (
            rf"\s*(?:{_ANSI_ESCAPE_PATTERN})*{_EMPTY_HEADING_SENTINEL}"
            rf"(?:{_ANSI_ESCAPE_PATTERN})*\s*"
        )
        break_pattern = (
            rf"\s*(?:{_ANSI_ESCAPE_PATTERN})*{_FORCED_BREAK_SENTINEL}"
            rf"(?:{_ANSI_ESCAPE_PATTERN})*\s*"
        )

        rendered = re.sub(empty_pattern, "\n", rendered)
        rendered = re.sub(break_pattern, "\n", rendered)
    return rendered


def _prompt_toolkit_available() -> bool:
    """Return True when prompt_toolkit can be imported."""

    return importlib.util.find_spec("prompt_toolkit") is not None


def _prompt_toolkit_components():
    """Return prompt_toolkit primitives when available, otherwise ``None``."""

    if not _prompt_toolkit_available():
        _add_fallback_notice(
            "prompt_toolkit unavailable: reverting to basic pager without hyperlink navigation."
        )
        return None

    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    return Application, KeyBindings, Layout, Window, FormattedTextControl, Style


def _build_formatted_text(
    lines: Sequence[str],
    hyperlinks_by_line: Dict[int, List[Hyperlink]],
    focused: Optional[Hyperlink],
) -> List[Tuple[str, str]]:
    """Return formatted text segments with hyperlink styling applied."""

    segments: List[Tuple[str, str]] = []
    for line_number, line in enumerate(lines):
        cursor = 0
        for link in hyperlinks_by_line.get(line_number, []):
            prefix = line[cursor : link.start]
            if prefix:
                segments.append(("", prefix))

            style = "class:hyperlink.focused"
            if not focused or focused.index != link.index:
                style = "class:hyperlink"
            segments.append((style, line[link.start : link.end]))
            cursor = link.end

        remainder = line[cursor:]
        segments.append(("", remainder + "\n"))
    return segments


def _align_focus(window: "Window", focus: Optional[Hyperlink]) -> None:
    """Scroll the viewport to reveal the focused hyperlink if needed."""

    if focus is None:
        return

    render_info = window.render_info
    height = render_info.window_height if render_info else 0
    top = window.vertical_scroll
    bottom = top + max(height - 1, 0)

    if focus.line < top:
        window.vertical_scroll = focus.line
    elif focus.line > bottom:
        window.vertical_scroll = max(focus.line - max(height - 1, 0), 0)


def _scroll_window(window: "Window", amount: int, total_lines: int) -> None:
    """Adjust vertical scroll safely within the document bounds."""

    render_info = window.render_info
    height = render_info.window_height if render_info else 0
    max_scroll = max(total_lines - max(height, 1), 0)
    new_scroll = min(max(window.vertical_scroll + amount, 0), max_scroll)
    window.vertical_scroll = new_scroll


def _attempt_prompt_toolkit_pager(text: str) -> bool:
    """Return True if text was paged interactively with prompt_toolkit."""

    components = _prompt_toolkit_components()
    if components is None or not sys.stdout.isatty():
        if not sys.stdout.isatty():
            _add_fallback_notice(
                "Interactive pager requires a TTY. Falling back to basic paging without hyperlink focus."
            )
        return False

    (
        Application,
        KeyBindings,
        Layout,
        Window,
        FormattedTextControl,
        Style,
    ) = components

    lines, hyperlinks, hyperlinks_by_line = normalize_hyperlinks(text.splitlines())
    navigator = HyperlinkNavigator(hyperlinks)

    def formatted_text() -> List[Tuple[str, str]]:
        return _build_formatted_text(lines, hyperlinks_by_line, navigator.focus)

    control = FormattedTextControl(
        formatted_text, focusable=False, show_cursor=False, focusable_windows=False
    )
    window = Window(content=control, wrap_lines=False, always_hide_cursor=True)

    bindings = KeyBindings()

    @bindings.add("q")
    @bindings.add("escape")
    @bindings.add("c-c")
    def _(event) -> None:  # type: ignore[override]
        event.app.exit()

    def _window_height() -> int:
        render_info = window.render_info
        return render_info.window_height if render_info else 0

    @bindings.add("tab")
    def _(event) -> None:  # type: ignore[override]
        focus = navigator.focus_next(window.vertical_scroll, max(_window_height(), 1))
        _align_focus(window, focus)
        event.app.invalidate()

    @bindings.add("s-tab")
    def _(event) -> None:  # type: ignore[override]
        focus = navigator.focus_previous(
            window.vertical_scroll, max(_window_height(), 1)
        )
        _align_focus(window, focus)
        event.app.invalidate()

    @bindings.add("down")
    @bindings.add("j")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, 1, len(lines))
        event.app.invalidate()

    @bindings.add("up")
    @bindings.add("k")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, -1, len(lines))
        event.app.invalidate()

    @bindings.add("pageup")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, -max(_window_height(), 1), len(lines))
        event.app.invalidate()

    @bindings.add("pagedown")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, max(_window_height(), 1), len(lines))
        event.app.invalidate()

    @bindings.add("home")
    def _(event) -> None:  # type: ignore[override]
        window.vertical_scroll = 0
        event.app.invalidate()

    @bindings.add("end")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, len(lines), len(lines))
        event.app.invalidate()

    style = Style.from_dict(
        {
            "hyperlink": "underline",
            "hyperlink.focused": "underline reverse",
        }
    )

    application = Application(
        layout=Layout(window),
        key_bindings=bindings,
        full_screen=True,
        style=style,
    )

    try:
        application.run()
    except Exception as error:  # pragma: no cover - defensive fallback
        _add_fallback_notice(
            "prompt_toolkit pager failed: falling back to basic pager. " f"({error})"
        )
        return False
    return True


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

    if _attempt_prompt_toolkit_pager(text):
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
