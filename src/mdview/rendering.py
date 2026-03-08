"""Core rendering and paging utilities for mdview.

The module keeps the Markdown-to-ANSI pipeline compact and drives an internal
text viewer path for interactive paging. All public functions are covered by
unit tests to ensure reliable behavior.
"""

import importlib.util
import re
import sys
import textwrap
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Callable,
    Dict,
    List,
    Match,
    Optional,
    Sequence,
    Tuple,
    Type,
)

from mdview.intake import ingest_content
from mdview.viewer import materialize_plain_text_lines
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

    def __init__(
        self,
        record: bool = False,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> None:
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
_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_IMAGE_PATTERN = re.compile(r"(?<!\\)!\[([^\]]*)\]\(([^)]*)\)")
_NUMERIC_CELL_PATTERN = re.compile(r"^[+-]?\d+(?:[.,]\d+)?%?$")


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


def _format_links(text: str, has_rich: bool) -> str:
    """Return content with inline Markdown links expanded for plain rendering."""

    if has_rich:
        return text

    def _replacement(match: Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        return f"{label} ({target})"

    return _LINK_PATTERN.sub(_replacement, text)


def _format_images(text: str, has_rich: bool) -> str:
    """Return content with inline Markdown images expanded in fallback mode."""

    if has_rich:
        return text

    def _replacement(match: Match[str]) -> str:
        alt_text = match.group(1).strip() or "[image]"
        target = match.group(2).strip()
        if not target:
            return f"{alt_text} (missing image URL)"

        # Optional title suffix is metadata-only for fallback visibility.
        url = target
        if ' "' in target:
            url = target.split(' "', 1)[0].strip()
        if not url:
            return f"{alt_text} (missing image URL)"
        return f"{alt_text} ({url})"

    return _IMAGE_PATTERN.sub(_replacement, text)


def _table_line_width(widths: Sequence[int]) -> int:
    """Return rendered table row width from cell widths."""

    if not widths:
        return 0
    return sum(widths) + (3 * len(widths)) + 1


def _fit_cell_min_width(text: str) -> int:
    """Return aggressive fit-first practical width for one table cell."""

    stripped = text.strip()
    if not stripped:
        return 1
    if len(stripped) <= 4:
        return len(stripped)
    if _NUMERIC_CELL_PATTERN.match(stripped):
        return min(len(stripped), 3)

    if any(char.isspace() for char in stripped):
        words = [word for word in re.split(r"\s+", stripped) if word]
        longest = max((len(word) for word in words), default=1)
        return min(len(stripped), max(3, min(longest, 8)))

    if any(char in stripped for char in "/._-:@") and len(stripped) > 8:
        return 6

    return min(len(stripped), 5)


def _shrink_widths_for_fit(
    widths: Sequence[int], min_widths: Sequence[int], target_width: int
) -> List[int]:
    """Greedily shrink columns toward min widths until fit or exhausted."""

    current = list(widths)
    while _table_line_width(current) > target_width:
        reducible = [
            index for index, width in enumerate(current) if width > min_widths[index]
        ]
        if not reducible:
            break
        chosen = max(
            reducible,
            key=lambda index: (
                current[index] - min_widths[index],
                current[index],
                -index,
            ),
        )
        current[chosen] -= 1
    return current


def _wrap_cell_lines(text: str, width: int, *, fit_first: bool) -> List[str]:
    """Return wrapped display lines for a single cell."""

    stripped = text.strip()
    if not stripped:
        return [""]
    if not fit_first:
        return [stripped]
    wrapped = textwrap.wrap(
        stripped,
        width=max(1, width),
        break_long_words=True,
        break_on_hyphens=True,
        drop_whitespace=False,
    )
    return wrapped or [""]


def _format_row_lines(
    row: Sequence[str],
    widths: Sequence[int],
    alignments: Sequence[str],
    *,
    fit_first: bool,
) -> List[str]:
    """Format one logical row into one or more rendered lines."""

    cell_lines: List[List[str]] = []
    for column, width in enumerate(widths):
        cell_text = row[column].strip() if column < len(row) else ""
        cell_lines.append(_wrap_cell_lines(cell_text, width, fit_first=fit_first))

    row_height = max((len(lines) for lines in cell_lines), default=1)
    rendered: List[str] = []
    for line_index in range(row_height):
        padded_cells: List[str] = []
        for column, width in enumerate(widths):
            fragment = (
                cell_lines[column][line_index]
                if line_index < len(cell_lines[column])
                else ""
            )
            alignment = alignments[column] if column < len(alignments) else "left"
            if alignment == "center":
                padded = fragment.center(width)
            elif alignment == "right":
                padded = fragment.rjust(width)
            else:
                padded = fragment.ljust(width)
            padded_cells.append(padded)
        rendered.append("| " + " | ".join(padded_cells) + " |")
    return rendered


def _format_divider_line(widths: Sequence[int], alignments: Sequence[str]) -> str:
    """Return the Markdown divider row for the chosen widths."""

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


def _format_table_block(
    lines: Sequence[str],
    start: int,
    *,
    viewport_width: Optional[int],
    readability_first_tables: bool,
) -> Tuple[List[str], int]:
    """Return formatted table rows and the index after the table block."""

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
    readability_widths: List[int] = []
    min_widths: List[int] = []
    for column in range(column_count):
        readable_width = 0
        fit_min = 1
        for row in rows:
            if column < len(row):
                text = row[column].strip()
                readable_width = max(readable_width, len(text))
                fit_min = max(fit_min, _fit_cell_min_width(text))
        if column < len(divider_cells):
            divider_width = len(divider_cells[column].strip(" :"))
            readable_width = max(readable_width, divider_width)
        readable_width = max(readable_width, 3)
        fit_min = max(min(fit_min, readable_width), 3)
        readability_widths.append(readable_width)
        min_widths.append(fit_min)

    fit_widths = list(readability_widths)
    if viewport_width is not None and viewport_width > 0:
        fit_widths = _shrink_widths_for_fit(fit_widths, min_widths, viewport_width)
    fit_can_avoid_overflow = (
        viewport_width is None
        or viewport_width <= 0
        or _table_line_width(fit_widths) <= viewport_width
    )

    if readability_first_tables:
        chosen_widths = readability_widths
        fit_first = False
    elif fit_can_avoid_overflow:
        chosen_widths = fit_widths
        fit_first = True
    else:
        chosen_widths = readability_widths
        fit_first = False

    formatted_lines: List[str] = []
    formatted_lines.extend(
        _format_row_lines(rows[0], chosen_widths, alignments, fit_first=fit_first)
    )
    formatted_lines.append(_format_divider_line(chosen_widths, alignments))
    for row in rows[1:]:
        formatted_lines.extend(
            _format_row_lines(row, chosen_widths, alignments, fit_first=fit_first)
        )

    return formatted_lines, index


def _format_pipe_tables(
    text: str,
    *,
    viewport_width: Optional[int] = None,
    readability_first_tables: bool = False,
) -> str:
    """Return content with pipe tables formatted under active width profile."""

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
            formatted, next_index = _format_table_block(
                lines,
                index,
                viewport_width=viewport_width,
                readability_first_tables=readability_first_tables,
            )
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


def _is_horizontal_rule_line(line: str) -> bool:
    """Return ``True`` when the line represents a horizontal rule marker."""

    stripped = line.strip()
    if not stripped:
        return False

    collapsed = stripped.replace(" ", "").replace("\t", "")
    marker: Optional[str] = None
    count = 0
    for char in collapsed:
        if char not in {"-", "*"}:
            return False
        if marker is None:
            marker = char
        elif char != marker:
            return False
        count += 1

    return count >= 3


def _normalize_horizontal_rules(text: str, has_rich: bool) -> str:
    """Normalize horizontal rule markers and preserve surrounding spacing."""

    lines = text.splitlines()
    output: List[str] = []
    rule_detected = False

    for index, line in enumerate(lines):
        if _is_horizontal_rule_line(line):
            rule_detected = True
            if output and output[-1].strip():
                output.append("")

            output.append("---")

            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            if next_line.strip():
                output.append("")

            continue

        output.append(line)

    if rule_detected and not has_rich:
        _add_fallback_notice(
            "Rich unavailable: rendering horizontal rules with plain separators."
        )

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


def _configure_heading_rendering() -> None:
    """Resize Markdown heading panels to avoid wrapping artifacts."""

    if not HAS_RICH:
        return

    try:
        from rich import box as rich_box
        from rich.markdown import Heading as RichHeading
        from rich.panel import Panel
        from rich.text import Text
    except Exception:  # pragma: no cover - defensive guard for optional import
        return

    def _compact_heading_console(self: "RichHeading", console: Console, options):
        text = self.text.copy()
        text.justify = "center"
        panel_width: Optional[int] = getattr(options, "max_width", None)
        if panel_width is None:
            panel_width = getattr(console, "width", None)
        if self.tag == "h1":
            yield Panel(
                text,
                box=rich_box.HEAVY,
                style="markdown.h1.border",
                expand=True,
                width=panel_width,
            )
        else:
            if self.tag == "h2":
                yield Text("")
            yield text

    RichHeading.__rich_console__ = _compact_heading_console


_configure_heading_rendering()


# Type alias for pager callables used in tests and potential future hooks.
Pager = Callable[[str], None]
SwitchDocument = Callable[[int, Optional[int]], Optional[str]]
UiEventLogger = Callable[[str, Dict[str, object]], None]
CurrentDocumentIndex = Callable[[], int]


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


def render_to_ansi(
    content: str,
    markdown: bool,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    reflow_mode: Optional[str] = None,
    readability_first_tables: bool = False,
) -> str:
    """Render the given content to ANSI-decorated text.

    When ``markdown`` is true, the content is parsed through ``rich``'s
    ``Markdown`` renderer; otherwise the text is printed verbatim. ``Console``
    is run in record mode so that the emitted ANSI escape sequences can be
    exported for paging. When Rich is unavailable, the fallback console and
    markdown stubs record plain text output without styling.

    Args:
        content: The document content to render.
        markdown: Whether to process the content as Markdown.
        width: Optional line width override used when rendering through Rich.
        height: Optional line height override to mirror viewport sizing.
        reflow_mode: Active reflow policy mode (``prose``, ``all``, ``none``).
        readability_first_tables: Force readability-first table layout profile.

    Returns:
        A string containing ANSI escape sequences suitable for paging.
    """

    # Route all sources through the shared intake model before rendering.
    document = ingest_content(content, markdown=markdown)
    source_text = document.to_source_text()
    if reflow_mode is None:
        reflow_mode = "prose" if markdown else "none"

    if not markdown:
        return _render_plain_text_document(
            document=document,
            reflow_mode=reflow_mode,
            width=width,
        )

    effective_width = width
    if markdown and effective_width is None:
        # Non-interactive rendering has no true viewport; prefer a wide default
        # to avoid brittle hard wraps in exported text and tests.
        effective_width = 130
    console = Console(record=True, width=effective_width, height=height)
    if markdown:
        trailing_newline = document.trailing_newline
        normalized = _normalize_heading_input(source_text, HAS_RICH)
        normalized = _normalize_bulleted_lists(normalized, HAS_RICH)
        normalized = _normalize_horizontal_rules(normalized, HAS_RICH)
        formatted = _format_pipe_tables(
            normalized,
            viewport_width=effective_width,
            readability_first_tables=readability_first_tables,
        )
        formatted = _format_images(formatted, HAS_RICH)
        formatted = _format_links(formatted, HAS_RICH)
        if trailing_newline:
            formatted += "\n"
        console.print(Markdown(formatted, code_theme="ansi_dark"))
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
        rendered = rendered.replace(_FORCED_BREAK_SENTINEL, "")
        rendered = rendered.replace(_EMPTY_HEADING_SENTINEL, "")
        rendered = _rstrip_exported_lines(rendered)
    return rendered


def _rstrip_exported_lines(text: str) -> str:
    """Strip right padding that Rich exports for fixed-width segments."""

    trailing_newline = text.endswith("\n")
    stripped = [line.rstrip() for line in text.splitlines()]
    normalized = "\n".join(stripped)
    if trailing_newline:
        normalized += "\n"
    return normalized


def _render_plain_text_document(
    *,
    document,
    reflow_mode: str,
    width: Optional[int],
) -> str:
    """Render a plain-text document according to the active reflow policy."""

    if reflow_mode == "none":
        return document.to_source_text()

    target_width = width if width and width > 0 else 78
    rendered_lines = materialize_plain_text_lines(
        document=document,
        reflow_mode=reflow_mode,
        width=target_width,
    )

    rendered = "\n".join(rendered_lines)
    if document.trailing_newline and not rendered.endswith("\n"):
        rendered += "\n"
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
    from prompt_toolkit.application.current import get_app
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    return (
        Application,
        KeyBindings,
        Layout,
        Window,
        FormattedTextControl,
        Style,
        get_app,
    )


def _visible_length(text: str) -> int:
    """Return the printable length of text without ANSI escapes."""

    return len(re.sub(_ANSI_ESCAPE_PATTERN, "", text))


def _build_formatted_text(
    lines: Sequence[str],
    hyperlinks_by_line: Dict[int, List[Hyperlink]],
    focused: Optional[Hyperlink],
    *,
    fill_width: Optional[int] = None,
) -> List[Tuple[str, str]]:
    """Return formatted text segments with hyperlink styling applied."""

    segments: List[Tuple[str, str]] = []
    for line_number, line in enumerate(lines):
        cursor = 0
        visible_length = 0
        line_segments: List[Tuple[str, str]] = []
        for link in hyperlinks_by_line.get(line_number, []):
            prefix = line[cursor : link.start]
            if prefix:
                line_segments.append(("", prefix))
                visible_length += _visible_length(prefix)

            style = "class:hyperlink.focused"
            if not focused or focused.index != link.index:
                style = "class:hyperlink"
            link_text = line[link.start : link.end]
            line_segments.append((style, link_text))
            visible_length += _visible_length(link_text)
            cursor = link.end

        remainder = line[cursor:]
        visible_length += _visible_length(remainder)
        if fill_width and fill_width > 0 and visible_length < fill_width:
            remainder += " " * (fill_width - visible_length)

        line_segments.append(("", remainder + "\n"))
        segments.extend(line_segments)
    return segments


def _align_focus(
    window: "Window",
    focus: Optional[Hyperlink],
    *,
    visible_width: Optional[int] = None,
) -> None:
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

    if visible_width is None or visible_width <= 0:
        return

    current_offset = max(int(getattr(window, "horizontal_scroll", 0)), 0)
    right_edge = current_offset + max(visible_width - 1, 0)
    if focus.start < current_offset:
        setattr(window, "horizontal_scroll", focus.start)
        return
    if focus.start > right_edge:
        margin = 2
        target_offset = max(focus.start - max(visible_width - margin - 1, 0), 0)
        setattr(window, "horizontal_scroll", target_offset)


def _scroll_window(window: "Window", amount: int, total_lines: int) -> None:
    """Adjust vertical scroll safely within the document bounds."""

    render_info = window.render_info
    height = render_info.window_height if render_info else 0
    max_scroll = max(total_lines - max(height, 1), 0)
    new_scroll = min(max(window.vertical_scroll + amount, 0), max_scroll)
    window.vertical_scroll = new_scroll


def _recenter_on_line(
    window: "Window", line: int, height: int, total_lines: int
) -> None:
    """Center the viewport on a target line when possible."""

    if height <= 0:
        return

    max_scroll = max(total_lines - height, 0)
    target_scroll = max(line - height // 2, 0)
    window.vertical_scroll = min(target_scroll, max_scroll)


def _attempt_prompt_toolkit_pager(
    text: str,
    *,
    render_on_resize: Optional[Callable[[int], str]] = None,
    switch_document: Optional[SwitchDocument] = None,
    ui_event_logger: Optional[UiEventLogger] = None,
    document_count: int = 1,
    current_document_index: Optional[CurrentDocumentIndex] = None,
) -> bool:
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
        get_app,
    ) = components

    current_text = text
    lines, hyperlinks, hyperlinks_by_line = normalize_hyperlinks(
        current_text.splitlines()
    )
    navigator = HyperlinkNavigator(hyperlinks)
    document_width = max((_visible_length(line) for line in lines), default=0)
    last_known_width: Optional[int] = None
    last_known_height: Optional[int] = None

    def _active_document_index() -> int:
        if current_document_index is None:
            return 0
        try:
            return max(int(current_document_index()), 0)
        except Exception:  # pragma: no cover - defensive callback guard
            return 0

    def _emit_ui_event(action: str, **context: object) -> None:
        if ui_event_logger is None:
            return
        payload: Dict[str, object] = {
            "document_index": _active_document_index() + 1,
            "document_count": max(document_count, 1),
            "vertical_scroll": int(getattr(window, "vertical_scroll", 0)),
            "horizontal_scroll": int(getattr(window, "horizontal_scroll", 0)),
        }
        payload.update(context)
        ui_event_logger(action, payload)

    def _max_horizontal_offset(width: Optional[int]) -> int:
        if width is None or width <= 0:
            return 0
        return max(document_width - width, 0)

    def _set_horizontal_offset(target: int) -> None:
        width = _window_width()
        max_offset = _max_horizontal_offset(width)
        clamped = min(max(target, 0), max_offset)
        setattr(window, "horizontal_scroll", clamped)

    def _restore_focus(previous: Optional[Hyperlink]) -> None:
        nonlocal navigator

        if previous is None:
            return

        for index, link in enumerate(navigator.hyperlinks):
            if (
                link.line == previous.line
                and link.text == previous.text
                and link.target == previous.target
            ):
                navigator._focus_index = index
                break

    def _refresh_rendered_text(width: Optional[int], height: Optional[int]) -> None:
        nonlocal current_text, lines, hyperlinks, hyperlinks_by_line
        nonlocal navigator, document_width
        nonlocal last_known_width, last_known_height

        if width is None or width <= 0 or height is None or height <= 0:
            return

        if last_known_width is None or last_known_height is None:
            last_known_width = width
            last_known_height = height
            return

        if width == last_known_width and height == last_known_height:
            return

        previous_center_line = window.vertical_scroll + (last_known_height // 2)
        previous_focus = navigator.focus
        if render_on_resize is not None:
            current_text = render_on_resize(width)
            lines, hyperlinks, hyperlinks_by_line = normalize_hyperlinks(
                current_text.splitlines()
            )
            navigator = HyperlinkNavigator(hyperlinks)
            _restore_focus(previous_focus)
            document_width = max((_visible_length(line) for line in lines), default=0)

        last_known_width = width
        last_known_height = height
        _set_horizontal_offset(int(getattr(window, "horizontal_scroll", 0)))
        _recenter_on_line(window, previous_center_line, height, len(lines))
        _emit_ui_event("resize", width=width, height=height)

    def _switch_to_document(event, delta: int, action: str) -> None:
        nonlocal current_text, lines, hyperlinks, hyperlinks_by_line
        nonlocal navigator, document_width

        if switch_document is None:
            _emit_ui_event(f"{action}-blocked")
            return
        width = _window_width()
        replacement = switch_document(delta, width)
        if replacement is None:
            _emit_ui_event(f"{action}-blocked")
            return

        current_text = replacement
        lines, hyperlinks, hyperlinks_by_line = normalize_hyperlinks(
            current_text.splitlines()
        )
        navigator = HyperlinkNavigator(hyperlinks)
        document_width = max((_visible_length(line) for line in lines), default=0)
        window.vertical_scroll = 0
        setattr(window, "horizontal_scroll", 0)
        _emit_ui_event(action, width=width)
        event.app.invalidate()

    def formatted_text() -> List[Tuple[str, str]]:
        width = _window_width()
        height = _window_height()
        _refresh_rendered_text(width, height)
        return _build_formatted_text(
            lines, hyperlinks_by_line, navigator.focus, fill_width=width
        )

    control = FormattedTextControl(
        formatted_text, focusable=False, show_cursor=False, focusable_windows=False
    )
    window = Window(content=control, wrap_lines=False, always_hide_cursor=True)

    bindings = KeyBindings()

    @bindings.add("q")
    @bindings.add("escape")
    @bindings.add("c-c")
    def _(event) -> None:  # type: ignore[override]
        _emit_ui_event("quit")
        event.app.exit()

    def _window_height() -> int:
        try:
            app = get_app()
            size = app.output.get_size()
            if size and getattr(size, "rows", 0) > 0:
                return size.rows
        except (AttributeError, RuntimeError):
            pass

        render_info = window.render_info
        return render_info.window_height if render_info else 0

    def _window_width() -> Optional[int]:
        try:
            app = get_app()
            size = app.output.get_size()
            if size and getattr(size, "columns", 0) > 0:
                return size.columns
        except (AttributeError, RuntimeError):
            pass

        render_info = window.render_info
        return render_info.window_width if render_info else None

    @bindings.add("tab")
    def _(event) -> None:  # type: ignore[override]
        focus = navigator.focus_next(window.vertical_scroll, max(_window_height(), 1))
        _align_focus(window, focus, visible_width=_window_width())
        _emit_ui_event("hyperlink-focus-next")
        event.app.invalidate()

    @bindings.add("s-tab")
    def _(event) -> None:  # type: ignore[override]
        focus = navigator.focus_previous(
            window.vertical_scroll, max(_window_height(), 1)
        )
        _align_focus(window, focus, visible_width=_window_width())
        _emit_ui_event("hyperlink-focus-previous")
        event.app.invalidate()

    @bindings.add("left")
    @bindings.add("h")
    def _(event) -> None:  # type: ignore[override]
        current = int(getattr(window, "horizontal_scroll", 0))
        _set_horizontal_offset(current - 1)
        _emit_ui_event("pan-left")
        event.app.invalidate()

    @bindings.add("right")
    @bindings.add("l")
    def _(event) -> None:  # type: ignore[override]
        current = int(getattr(window, "horizontal_scroll", 0))
        _set_horizontal_offset(current + 1)
        _emit_ui_event("pan-right")
        event.app.invalidate()

    @bindings.add("down")
    @bindings.add("j")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, 1, len(lines))
        _emit_ui_event("scroll-down")
        event.app.invalidate()

    @bindings.add("up")
    @bindings.add("k")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, -1, len(lines))
        _emit_ui_event("scroll-up")
        event.app.invalidate()

    @bindings.add("pageup")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, -max(_window_height(), 1), len(lines))
        _emit_ui_event("page-up")
        event.app.invalidate()

    @bindings.add("pagedown")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, max(_window_height(), 1), len(lines))
        _emit_ui_event("page-down")
        event.app.invalidate()

    @bindings.add("home")
    def _(event) -> None:  # type: ignore[override]
        window.vertical_scroll = 0
        _emit_ui_event("jump-home")
        event.app.invalidate()

    @bindings.add("end")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, len(lines), len(lines))
        _emit_ui_event("jump-end")
        event.app.invalidate()

    @bindings.add("n")
    def _(event) -> None:  # type: ignore[override]
        _switch_to_document(event, 1, "document-next")

    @bindings.add(":", "n")
    def _(event) -> None:  # type: ignore[override]
        _switch_to_document(event, 1, "document-next")

    @bindings.add("p")
    def _(event) -> None:  # type: ignore[override]
        _switch_to_document(event, -1, "document-previous")

    @bindings.add(":", "p")
    def _(event) -> None:  # type: ignore[override]
        _switch_to_document(event, -1, "document-previous")

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
            "prompt_toolkit pager failed: falling back to non-interactive "
            f"output. ({error})"
        )
        return False
    return True


def page_text(
    text: str,
    pager: Optional[Pager] = None,
    *,
    render_on_resize: Optional[Callable[[int], str]] = None,
    switch_document: Optional[SwitchDocument] = None,
    ui_event_logger: Optional[UiEventLogger] = None,
    document_count: int = 1,
    current_document_index: Optional[CurrentDocumentIndex] = None,
) -> None:
    """Display rendered text using the internal viewing stack.

    Args:
        text: Rendered ANSI text to display.
        pager: Optional callable to handle paging (primarily for testing).
        render_on_resize: Optional callable used to regenerate the text when
            the interactive pager detects a change in the terminal width.
        switch_document: Optional callback to load the next/previous
            document. Receives delta (+1/-1) and current viewport width.
        ui_event_logger: Optional callback that receives user action events.
        document_count: Number of open documents in the active session.
        current_document_index: Callback returning the active 0-based index.
    """

    if pager:
        pager(text)
        return

    if _attempt_prompt_toolkit_pager(
        text,
        render_on_resize=render_on_resize,
        switch_document=switch_document,
        ui_event_logger=ui_event_logger,
        document_count=document_count,
        current_document_index=current_document_index,
    ):
        return
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()
