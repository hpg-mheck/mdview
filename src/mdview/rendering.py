"""Core rendering and paging utilities for mdview.

The module keeps the Markdown-to-ANSI pipeline compact and drives an internal
text viewer path for interactive paging. The hard parts live in three places:
Markdown normalization before Rich sees the text, ANSI-to-prompt_toolkit
translation for the interactive pager, and defensive fallbacks when optional
dependencies are missing. Keep those boundaries legible; regressions in this
module tend to come from "simplifying" a path whose ordering or state owner
was more important than it first looked.
"""

import importlib.util
import io
import json
import re
import sys
import textwrap
import threading
from datetime import datetime, timezone
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
        file: Optional[io.StringIO] = None,
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
_SOFT_BREAK_SENTINEL = "<!--MDVIEWHEADINGBREAK-->"
_ANSI_ESCAPE_PATTERN = r"\x1b\[[0-?]*[ -/]*[@-~]"
_OSC_ESCAPE_PATTERN = r"\x1b\][^\x1b\x07]*(?:\x1b\\|\x07)"
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
                # Rich treats indented ``#`` headings as literal text unless we
                # escape the marker and then force a hard paragraph break after
                # it. Keep the paired structural sentinels here; collapsing
                # them back into a single generic break marker reopens wrapping
                # bugs that the heading tests cover.
                normalized.append(f"{line[: len(line) - len(stripped)]}\\{stripped}")
                normalized.extend([_FORCED_BREAK_SENTINEL, _FORCED_BREAK_SENTINEL])
                continue

        normalized.append(line)

    return "\n".join(normalized)


def _normalize_bulleted_lists(text: str, has_rich: bool) -> str:
    """Ensure bulleted list blocks remain visually separated."""

    lines = text.splitlines()
    output: List[str] = []
    in_list = False
    current_marker: Optional[str] = None

    def _append_break(*, structural: bool) -> None:
        if has_rich:
            output.append("")
            # Keep structural and soft breaks distinct. Structural breaks must
            # survive long enough to force Rich out of list context; soft
            # breaks must *not* consume visible wrap width inside prose. This
            # distinction is easy to "simplify" away and doing so reintroduces
            # the width-sensitive list/paragraph wrap regression.
            marker = _FORCED_BREAK_SENTINEL if structural else _SOFT_BREAK_SENTINEL
            output.extend([marker, marker])
        else:
            output.append("")

    def _is_indented_list_marker(line: str) -> bool:
        stripped = line.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            return True
        return bool(re.match(r"\d+\.\s", stripped))

    for line in lines:
        stripped = line.lstrip()
        is_bullet = stripped.startswith("- ") or stripped.startswith("* ")
        marker = stripped[:1] if is_bullet else None

        if is_bullet:
            if not in_list and output and output[-1].strip():
                _append_break(structural=False)
            elif in_list and marker != current_marker:
                _append_break(structural=False)

            output.append(line)
            in_list = True
            current_marker = marker
            continue

        if in_list:
            if not line.strip():
                _append_break(structural=False)
                in_list = False
                current_marker = None
                continue

            if len(line) > len(line.lstrip(" \t")) and not _is_indented_list_marker(
                line
            ):
                output.append(line)
                continue

            if output and output[-1].strip() and line.strip():
                _append_break(structural=_is_indented_list_marker(line))
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
AutomationReplayEvent = Tuple[float, str]


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
    capture_stream = io.StringIO()
    console = Console(
        record=True,
        width=effective_width,
        height=height,
        file=capture_stream,
    )
    if markdown:
        trailing_newline = document.trailing_newline
        # The ordering here is intentional. Each normalization pass prepares
        # the source for the next one, and later cleanup expects the current
        # sentinel shapes exactly as produced below.
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
            rf"\s*(?:{_ANSI_ESCAPE_PATTERN})*{re.escape(_EMPTY_HEADING_SENTINEL)}"
            rf"(?:{_ANSI_ESCAPE_PATTERN})*\s*"
        )
        break_pattern = (
            rf"\s*(?:{_ANSI_ESCAPE_PATTERN})*{re.escape(_FORCED_BREAK_SENTINEL)}"
            rf"(?:{_ANSI_ESCAPE_PATTERN})*\s*"
        )
        soft_break_pattern = (
            rf"\s*(?:{_ANSI_ESCAPE_PATTERN})*{re.escape(_SOFT_BREAK_SENTINEL)}"
            rf"(?:{_ANSI_ESCAPE_PATTERN})*\s*"
        )

        rendered = re.sub(empty_pattern, "\n", rendered)
        rendered = re.sub(break_pattern, "\n", rendered)
        rendered = re.sub(soft_break_pattern, "\n", rendered)
        rendered = rendered.replace(_FORCED_BREAK_SENTINEL, "")
        rendered = rendered.replace(_SOFT_BREAK_SENTINEL, "")
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
    from prompt_toolkit.layout.containers import Float, FloatContainer, Window
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
        FloatContainer,
        Float,
    )


def _visible_length(text: str) -> int:
    """Return the printable length of text without ANSI escapes."""

    sanitized = re.sub(_OSC_ESCAPE_PATTERN, "", text)
    return len(re.sub(_ANSI_ESCAPE_PATTERN, "", sanitized))


def _strip_terminal_escape_sequences(text: str) -> str:
    """Return text with ANSI and OSC terminal control sequences removed."""

    without_osc = re.sub(_OSC_ESCAPE_PATTERN, "", text)
    return re.sub(_ANSI_ESCAPE_PATTERN, "", without_osc)


def _ansi_line_to_formatted_segments(line: str) -> List[Tuple[str, str]]:
    """Return prompt_toolkit-compatible formatted segments for one ANSI line."""

    sanitized = re.sub(_OSC_ESCAPE_PATTERN, "", line)
    try:
        from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    except Exception:
        return [("", re.sub(_ANSI_ESCAPE_PATTERN, "", sanitized))]

    segments: List[Tuple[str, str]] = []
    for fragment in to_formatted_text(ANSI(sanitized)):
        if len(fragment) < 2:
            continue
        style = str(fragment[0] or "")
        text = str(fragment[1] or "")
        if text:
            segments.append((style, text))
    return segments


def _normalize_cell_character(value: object) -> str:
    """Return one printable character for a framebuffer cell snapshot."""

    if value is None:
        return " "
    if not isinstance(value, str):
        value = str(value)
    if not value:
        return " "
    return value[0]


def _to_ascii_cell(character: str) -> str:
    """Return deterministic ASCII output for a captured framebuffer cell."""

    if not character:
        return " "
    codepoint = ord(character[0])
    if 32 <= codepoint <= 126:
        return character[0]
    return "?"


def _parse_style_attributes(style_value: str) -> Dict[str, object]:
    """Return best-effort parsed style attributes from prompt_toolkit style."""

    attributes: Dict[str, object] = {
        "foreground": None,
        "background": None,
        "bold": False,
        "italic": False,
        "underline": False,
        "blink": False,
        "reverse": False,
        "hidden": False,
        "strike": False,
        "dim": False,
    }
    for token in style_value.split():
        if token.startswith("fg:"):
            attributes["foreground"] = token[3:]
            continue
        if token.startswith("bg:"):
            attributes["background"] = token[3:]
            continue
        if token in attributes and isinstance(attributes[token], bool):
            attributes[token] = True
            continue
        if token == "strikethrough":
            attributes["strike"] = True
    return attributes


def _make_cell_snapshot(
    *,
    row: int,
    column: int,
    character: str,
    style_value: str,
) -> Dict[str, object]:
    """Return standardized timeout-capture metadata for one framebuffer cell."""

    normalized = _normalize_cell_character(character)
    return {
        "row": row,
        "column": column,
        "character_utf8": normalized,
        "character_ascii": _to_ascii_cell(normalized),
        "style": style_value,
        "attributes": _parse_style_attributes(style_value),
    }


def _capture_prompt_toolkit_framebuffer(
    application: object,
    *,
    width: int,
    height: int,
) -> Optional[List[List[Dict[str, object]]]]:
    """Return visible rows from prompt_toolkit's renderer when available."""

    if width <= 0 or height <= 0:
        return None

    renderer = getattr(application, "renderer", None)
    screen = getattr(renderer, "last_rendered_screen", None)
    data_buffer = getattr(screen, "data_buffer", None)
    if data_buffer is None:
        return None

    rows: List[List[Dict[str, object]]] = []
    for row_index in range(height):
        row_buffer = data_buffer.get(row_index, {})
        cells: List[Dict[str, object]] = []
        for column_index in range(width):
            cell = row_buffer.get(column_index)
            character = _normalize_cell_character(getattr(cell, "char", " "))
            style_value = ""
            if cell is not None:
                style_value = str(getattr(cell, "style", "") or "")
            cells.append(
                _make_cell_snapshot(
                    row=row_index,
                    column=column_index,
                    character=character,
                    style_value=style_value,
                )
            )
        rows.append(cells)
    return rows


def _capture_text_buffer_framebuffer(
    *,
    lines: Sequence[str],
    vertical_scroll: int,
    horizontal_scroll: int,
    width: int,
    height: int,
) -> List[List[Dict[str, object]]]:
    """Return a synthetic viewport capture from the current text buffer."""

    safe_width = max(int(width), 1)
    safe_height = max(int(height), 1)
    top = max(int(vertical_scroll), 0)
    left = max(int(horizontal_scroll), 0)
    rows: List[List[Dict[str, object]]] = []

    for row_index in range(safe_height):
        line_index = top + row_index
        source = lines[line_index] if line_index < len(lines) else ""
        plain = _strip_terminal_escape_sequences(source)
        visible = plain[left : left + safe_width]
        if len(visible) < safe_width:
            visible += " " * (safe_width - len(visible))
        cells: List[Dict[str, object]] = []
        for column_index in range(safe_width):
            cells.append(
                _make_cell_snapshot(
                    row=row_index,
                    column=column_index,
                    character=visible[column_index],
                    style_value="",
                )
            )
        rows.append(cells)
    return rows


def _ascii_lines_from_cells(
    cell_rows: Sequence[Sequence[Dict[str, object]]],
) -> List[str]:
    """Return fixed-width ASCII lines from captured framebuffer cells."""

    lines: List[str] = []
    for row in cell_rows:
        ascii_chars = [str(cell.get("character_ascii", " "))[:1] for cell in row]
        lines.append("".join(ascii_chars))
    return lines


def _write_timeout_framebuffer_capture(
    *,
    target_basename: Path,
    cell_rows: Sequence[Sequence[Dict[str, object]]],
    width: int,
    height: int,
    capture_source: str,
    vertical_scroll: int,
    horizontal_scroll: int,
    document_index: int,
    document_count: int,
) -> Tuple[Path, Path]:
    """Write timeout framebuffer text+attrs artifacts and return their paths."""

    resolved_base = target_basename.expanduser().resolve()
    resolved_base.parent.mkdir(parents=True, exist_ok=True)
    txt_path = resolved_base.parent / f"{resolved_base.name}.txt"
    attrs_path = resolved_base.parent / f"{resolved_base.name}.attrs.json"

    payload = {
        "format": "mdview-timeout-framebuffer-attrs-v1",
        "captured_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "capture_source": capture_source,
        "viewport_columns": width,
        "viewport_rows": height,
        "vertical_scroll": vertical_scroll,
        "horizontal_scroll": horizontal_scroll,
        "document_index": document_index,
        "document_count": document_count,
        "txt_path": str(txt_path),
        "attrs_path": str(attrs_path),
        "rows": [
            {
                "row": row_index,
                "cells": list(row_cells),
            }
            for row_index, row_cells in enumerate(cell_rows)
        ],
    }
    ascii_lines = _ascii_lines_from_cells(cell_rows)
    with txt_path.open("w", encoding="ascii", newline="") as text_file:
        for line in ascii_lines:
            text_file.write(line)
            text_file.write("\r\n")

    attrs_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return txt_path, attrs_path


def _build_formatted_text(
    lines: Sequence[str],
    hyperlinks_by_line: Dict[int, List[Hyperlink]],
    focused: Optional[Hyperlink],
    *,
    fill_width: Optional[int] = None,
    overlay_line: Optional[int] = None,
    overlay_column: Optional[int] = None,
    overlay_character: Optional[str] = None,
    overlay_style: str = "class:redraw-check-digit",
) -> List[Tuple[str, str]]:
    """Return formatted text segments with hyperlink styling applied."""

    segments: List[Tuple[str, str]] = []
    for line_number, line in enumerate(lines):
        required_width = fill_width
        if overlay_line == line_number and overlay_column is not None:
            # Pad first, then overlay. The check digit and similar overlays are
            # defined in absolute viewport cells, so they must be able to land
            # past the natural text width without shifting from frame to frame.
            required_width = max(fill_width or 0, overlay_column + 1)

        line_links = hyperlinks_by_line.get(line_number, [])
        if not line_links:
            ansi_segments = _ansi_line_to_formatted_segments(line)
            visible_length = sum(len(text) for _, text in ansi_segments)
            if (
                required_width
                and required_width > 0
                and visible_length < required_width
            ):
                ansi_segments.append(("", " " * (required_width - visible_length)))
            ansi_segments.append(("", "\n"))
            if (
                overlay_line == line_number
                and overlay_column is not None
                and overlay_character is not None
            ):
                ansi_segments = _overlay_formatted_cell(
                    ansi_segments,
                    target_column=overlay_column,
                    replacement=overlay_character,
                    replacement_style=overlay_style,
                )
            segments.extend(ansi_segments)
            continue

        plain_line = _strip_terminal_escape_sequences(line)
        cursor = 0
        visible_length = 0
        line_segments: List[Tuple[str, str]] = []
        for link in line_links:
            prefix = plain_line[cursor : link.start]
            if prefix:
                line_segments.append(("", prefix))
                visible_length += _visible_length(prefix)

            style = "class:hyperlink.focused"
            if not focused or focused.index != link.index:
                style = "class:hyperlink"
            link_text = plain_line[link.start : link.end]
            line_segments.append((style, link_text))
            visible_length += _visible_length(link_text)
            cursor = link.end

        remainder = plain_line[cursor:]
        visible_length += _visible_length(remainder)
        if required_width and required_width > 0 and visible_length < required_width:
            remainder += " " * (required_width - visible_length)

        line_segments.append(("", remainder + "\n"))
        if (
            overlay_line == line_number
            and overlay_column is not None
            and overlay_character is not None
        ):
            line_segments = _overlay_formatted_cell(
                line_segments,
                target_column=overlay_column,
                replacement=overlay_character,
                replacement_style=overlay_style,
            )
        segments.extend(line_segments)

    if overlay_line is not None and overlay_character is not None:
        blank_width = fill_width or 0
        if overlay_column is not None:
            blank_width = max(blank_width, overlay_column + 1)
        for line_number in range(len(lines), overlay_line + 1):
            blank_segments: List[Tuple[str, str]] = []
            if blank_width > 0:
                # Preserve the requested viewport footprint even when the
                # overlay targets a line past the end of the document.
                blank_segments.append(("", " " * blank_width))
            blank_segments.append(("", "\n"))
            if overlay_line == line_number and overlay_column is not None:
                blank_segments = _overlay_formatted_cell(
                    blank_segments,
                    target_column=overlay_column,
                    replacement=overlay_character,
                    replacement_style=overlay_style,
                )
            segments.extend(blank_segments)
    return segments


def _append_formatted_segment(
    segments: List[Tuple[str, str]], style: str, text: str
) -> None:
    """Append formatted text while coalescing adjacent identical styles."""

    if not text:
        return
    if segments and segments[-1][0] == style:
        previous_style, previous_text = segments[-1]
        segments[-1] = (previous_style, previous_text + text)
        return
    segments.append((style, text))


def _overlay_formatted_cell(
    segments: Sequence[Tuple[str, str]],
    *,
    target_column: int,
    replacement: str,
    replacement_style: str,
) -> List[Tuple[str, str]]:
    """Return one line of formatted text with one visible cell replaced."""

    if target_column < 0 or not replacement:
        return list(segments)

    visible_column = 0
    replaced = False
    overlaid: List[Tuple[str, str]] = []
    for style, text in segments:
        for character in text:
            if character == "\n":
                _append_formatted_segment(overlaid, style, character)
                continue

            width = _visible_length(character)
            if width <= 0:
                _append_formatted_segment(overlaid, style, character)
                continue

            if not replaced and visible_column <= target_column < (
                visible_column + width
            ):
                # Replace exactly one visible cell while preserving the width
                # footprint of wide characters. The framebuffer capture tests
                # depend on this staying cell-stable.
                _append_formatted_segment(
                    overlaid,
                    replacement_style,
                    replacement,
                )
                if width > 1:
                    _append_formatted_segment(overlaid, style, " " * (width - 1))
                replaced = True
            else:
                _append_formatted_segment(overlaid, style, character)
            visible_column += width
    return overlaid


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


class _FallbackKeyPress:
    """Compatibility key-press object used when prompt_toolkit is absent."""

    def __init__(self, key: object, data: Optional[str] = None) -> None:
        self.key = key
        self.data = data


def _normalize_automation_key_name(name: str) -> str:
    """Normalize one automation key token into parser-friendly form."""

    stripped = name.strip()
    if not stripped:
        raise ValueError("automation key token cannot be empty")
    if len(stripped) == 1:
        return stripped

    normalized = stripped.lower()
    normalized = normalized.replace("control-", "c-")
    normalized = normalized.replace("ctrl-", "c-")
    normalized = normalized.replace("meta-", "m-")
    normalized = normalized.replace("alt-", "m-")
    if normalized.startswith("c-") and len(normalized) == 3:
        return f"c-{normalized[-1]}"
    return normalized


def _expand_automation_key_token(token: str) -> List[str]:
    """Expand one automation token into one or more prompt key names."""

    stripped = token.strip()
    if not stripped:
        raise ValueError("automation key token cannot be empty")

    if "+" in stripped:
        parts = [part.strip() for part in stripped.split("+")]
        if any(not part for part in parts):
            raise ValueError(f"invalid automation key token: {token!r}")

        meta_count = 0
        control = False
        key_part: Optional[str] = None
        for part in parts:
            lowered = part.lower()
            if lowered in {"m", "meta", "alt"}:
                meta_count += 1
                continue
            if lowered in {"c", "ctrl", "control"}:
                control = True
                continue
            if key_part is not None:
                raise ValueError(
                    "automation token with '+' must contain one key plus "
                    f"modifiers: {token!r}"
                )
            key_part = part

        if key_part is None:
            raise ValueError(f"missing key name in automation token: {token!r}")

        base = _normalize_automation_key_name(key_part)
        if control:
            if len(base) == 1:
                base = f"c-{base.lower()}"
            elif base == "space":
                base = "c-space"
            elif not base.startswith("c-"):
                base = f"c-{base}"
        return ["escape"] * meta_count + [base]

    normalized = _normalize_automation_key_name(stripped)
    if normalized == "-":
        return [normalized]

    parts = normalized.split("-")
    meta_count = sum(1 for part in parts if part == "m")
    if meta_count == 0:
        return [normalized]

    remainder = [part for part in parts if part != "m"]
    if not remainder:
        raise ValueError(f"missing key name after meta modifier: {token!r}")
    base = "-".join(remainder)
    return ["escape"] * meta_count + [base]


def _parse_automation_key_token(token: str) -> object:
    """Parse one prompt key token, using prompt_toolkit when available."""

    try:
        from prompt_toolkit.key_binding.key_bindings import _parse_key
    except Exception:
        if len(token) == 1:
            return token
        if token in {
            "down",
            "up",
            "left",
            "right",
            "pageup",
            "pagedown",
            "home",
            "end",
            "escape",
            "tab",
            "s-tab",
            "enter",
            "space",
        }:
            return token
        if re.fullmatch(r"c-[a-z]", token):
            return token
        if token == "c-space":
            return token
        raise ValueError(f"invalid automation key token: {token!r}")

    try:
        return _parse_key(token)
    except ValueError as error:
        raise ValueError(f"invalid automation key token: {token!r}") from error


def _build_key_press(key: object, data: Optional[str] = None) -> object:
    """Create a key-press object with prompt_toolkit or fallback shape."""

    try:
        from prompt_toolkit.key_binding.key_processor import KeyPress
    except Exception:
        return _FallbackKeyPress(key=key, data=data)
    return KeyPress(key=key, data=data)


def _build_automation_key_presses(key_spec: str) -> List[object]:
    """Return parsed key presses for one automation key specification."""

    spec = key_spec.strip()
    if not spec:
        raise ValueError("automation key spec cannot be empty")

    if spec.startswith("vt100:"):
        encoded = spec[len("vt100:") :]
        if not encoded:
            raise ValueError("vt100 automation key spec cannot be empty")
        try:
            from prompt_toolkit.input.vt100_parser import Vt100Parser
        except Exception as error:
            raise ValueError(
                "vt100 automation key specs require prompt_toolkit support"
            ) from error

        parsed: List[object] = []
        parser = Vt100Parser(parsed.append)
        parser.feed_and_flush(encoded)
        if not parsed:
            raise ValueError("vt100 automation key spec produced no key presses")
        return parsed

    tokens: List[str] = []
    for chunk in spec.split():
        tokens.extend(_expand_automation_key_token(chunk))

    if not tokens:
        raise ValueError("automation key spec produced no key tokens")

    return [_build_key_press(_parse_automation_key_token(token)) for token in tokens]


def _attempt_prompt_toolkit_pager(
    text: str,
    *,
    render_on_resize: Optional[Callable[[int], str]] = None,
    switch_document: Optional[SwitchDocument] = None,
    ui_event_logger: Optional[UiEventLogger] = None,
    document_count: int = 1,
    current_document_index: Optional[CurrentDocumentIndex] = None,
    automation_timeout: Optional[float] = None,
    automation_replay: Optional[Sequence[AutomationReplayEvent]] = None,
    automation_timeout_screenshot_basename: Optional[Path] = None,
    viewport_columns: Optional[int] = None,
    viewport_rows: Optional[int] = None,
    redraw_check_digit: bool = False,
) -> bool:
    """Return True if text was paged interactively with prompt_toolkit."""

    components = _prompt_toolkit_components()
    if components is None or not sys.stdout.isatty():
        if automation_timeout is not None and automation_timeout_screenshot_basename:
            _add_fallback_notice(
                "Automation timeout screenshot requested, but interactive pager "
                "is unavailable; no timeout-capture artifacts were written."
            )
        if automation_replay:
            _add_fallback_notice(
                "Automation key replay requested, but interactive pager is "
                "unavailable; replay was skipped."
            )
        if redraw_check_digit:
            _add_fallback_notice(
                "Redraw check digit requested, but interactive pager is "
                "unavailable; overlay was skipped."
            )
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
    ) = components[:7]
    FloatContainer = components[7] if len(components) > 7 else None
    Float = components[8] if len(components) > 8 else None

    current_text = text
    lines, hyperlinks, hyperlinks_by_line = normalize_hyperlinks(
        current_text.splitlines()
    )
    navigator = HyperlinkNavigator(hyperlinks)
    document_width = max((_visible_length(line) for line in lines), default=0)
    last_known_width: Optional[int] = None
    last_known_height: Optional[int] = None
    # Track viewport scroll in our own state and feed it back to prompt_toolkit
    # through the supported scroll callbacks below. Do not rely only on direct
    # ``window.vertical_scroll`` mutation here; prompt_toolkit may otherwise
    # snap back to the hidden cursor position in live terminals.
    viewport_vertical_scroll = 0
    viewport_horizontal_scroll = 0
    forced_columns = (
        max(int(viewport_columns), 1) if viewport_columns is not None else None
    )
    forced_rows = max(int(viewport_rows), 1) if viewport_rows is not None else None
    redraw_check_digit_counter = 0
    # A FloatContainer overlay keeps the check digit pinned to the screen
    # center instead of letting it drift with the scrolled document content.
    floating_redraw_check_digit = (
        redraw_check_digit and FloatContainer is not None and Float is not None
    )

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
            "vertical_scroll": viewport_vertical_scroll,
            "horizontal_scroll": viewport_horizontal_scroll,
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
        nonlocal viewport_horizontal_scroll
        viewport_horizontal_scroll = clamped
        setattr(window, "horizontal_scroll", clamped)

    def _sync_viewport_state_from_window() -> None:
        nonlocal viewport_vertical_scroll, viewport_horizontal_scroll
        # Keep the mirrored state normalized in one place. Several callbacks
        # emit UI events, restore focus, or rerender based on these values.
        viewport_vertical_scroll = max(int(getattr(window, "vertical_scroll", 0)), 0)
        viewport_horizontal_scroll = max(
            int(getattr(window, "horizontal_scroll", 0)),
            0,
        )

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

        # Preserve the reader's rough center point across width changes so
        # pinch-zoom and resize flows feel stable instead of jumping back to
        # the top on every geometry event.
        previous_center_line = viewport_vertical_scroll + (last_known_height // 2)
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
        _set_horizontal_offset(viewport_horizontal_scroll)
        _recenter_on_line(window, previous_center_line, height, len(lines))
        _sync_viewport_state_from_window()
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
        nonlocal viewport_vertical_scroll, viewport_horizontal_scroll
        # Document switches intentionally reset viewport position. Reusing the
        # old scroll offsets across unrelated documents makes navigation and
        # automation traces much harder to reason about.
        viewport_vertical_scroll = 0
        viewport_horizontal_scroll = 0
        window.vertical_scroll = 0
        setattr(window, "horizontal_scroll", 0)
        _emit_ui_event(action, width=width)
        event.app.invalidate()

    def formatted_text() -> List[Tuple[str, str]]:
        nonlocal redraw_check_digit_counter
        width = _window_width()
        height = _window_height()
        _refresh_rendered_text(width, height)
        overlay_line: Optional[int] = None
        overlay_column: Optional[int] = None
        overlay_character: Optional[str] = None
        if (
            redraw_check_digit
            and not floating_redraw_check_digit
            and width
            and width > 0
            and height > 0
        ):
            # Non-floating overlays are expressed in document coordinates so
            # the formatter can stamp the digit into the correct absolute cell
            # after scroll offsets have been applied.
            overlay_line = viewport_vertical_scroll + ((height - 1) // 2)
            overlay_column = viewport_horizontal_scroll + ((width - 1) // 2)
            overlay_character = str(redraw_check_digit_counter % 10)
            redraw_check_digit_counter = (redraw_check_digit_counter + 1) % 10
        return _build_formatted_text(
            lines,
            hyperlinks_by_line,
            navigator.focus,
            fill_width=width,
            overlay_line=overlay_line,
            overlay_column=overlay_column,
            overlay_character=overlay_character,
        )

    class _HiddenCursorPosition:
        def __init__(self, x: int, y: int) -> None:
            self.x = x
            self.y = y

    # Keep the hidden cursor aligned with the viewport origin. prompt_toolkit
    # uses cursor position during scroll calculations even when the cursor is
    # invisible, so this is part of the scrolling contract, not dead code.
    control = FormattedTextControl(
        formatted_text,
        focusable=False,
        show_cursor=False,
        get_cursor_position=lambda: _HiddenCursorPosition(
            viewport_horizontal_scroll,
            viewport_vertical_scroll,
        ),
    )
    window = Window(
        content=control,
        wrap_lines=False,
        always_hide_cursor=True,
        get_vertical_scroll=lambda _: viewport_vertical_scroll,
        get_horizontal_scroll=lambda _: viewport_horizontal_scroll,
    )
    _sync_viewport_state_from_window()
    overlay_float = None
    if floating_redraw_check_digit:
        overlay_control = FormattedTextControl(
            lambda: [
                (
                    "class:redraw-check-digit",
                    str(redraw_check_digit_counter % 10),
                )
            ],
            focusable=False,
            show_cursor=False,
        )
        overlay_window = Window(
            content=overlay_control,
            width=1,
            height=1,
            dont_extend_width=True,
            dont_extend_height=True,
            always_hide_cursor=True,
        )
        overlay_float = Float(
            content=overlay_window,
            left=0,
            top=0,
            transparent=True,
            z_index=10,
        )
        root_container = FloatContainer(content=window, floats=[overlay_float])
    else:
        root_container = window

    bindings = KeyBindings()

    def _request_quit(app) -> None:
        _emit_ui_event("quit")
        app.exit()

    @bindings.add("q")
    @bindings.add("c-c")
    def _(event) -> None:  # type: ignore[override]
        _request_quit(event.app)

    def _window_height() -> int:
        if forced_rows is not None:
            return forced_rows
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
        if forced_columns is not None:
            return forced_columns
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
        _sync_viewport_state_from_window()
        _emit_ui_event("hyperlink-focus-next")
        event.app.invalidate()

    @bindings.add("s-tab")
    def _(event) -> None:  # type: ignore[override]
        focus = navigator.focus_previous(
            window.vertical_scroll, max(_window_height(), 1)
        )
        _align_focus(window, focus, visible_width=_window_width())
        _sync_viewport_state_from_window()
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
    @bindings.add("s-down")
    @bindings.add("c-down")
    @bindings.add("c-s-down")
    @bindings.add("j")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, 1, len(lines))
        _sync_viewport_state_from_window()
        _emit_ui_event("scroll-down")
        event.app.invalidate()

    @bindings.add("up")
    @bindings.add("s-up")
    @bindings.add("c-up")
    @bindings.add("c-s-up")
    @bindings.add("k")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, -1, len(lines))
        _sync_viewport_state_from_window()
        _emit_ui_event("scroll-up")
        event.app.invalidate()

    @bindings.add("pageup")
    @bindings.add("s-pageup")
    @bindings.add("c-pageup")
    @bindings.add("c-s-pageup")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, -max(_window_height(), 1), len(lines))
        _sync_viewport_state_from_window()
        _emit_ui_event("page-up")
        event.app.invalidate()

    @bindings.add("pagedown")
    @bindings.add("s-pagedown")
    @bindings.add("c-pagedown")
    @bindings.add("c-s-pagedown")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, max(_window_height(), 1), len(lines))
        _sync_viewport_state_from_window()
        _emit_ui_event("page-down")
        event.app.invalidate()

    @bindings.add("home")
    def _(event) -> None:  # type: ignore[override]
        window.vertical_scroll = 0
        _sync_viewport_state_from_window()
        _emit_ui_event("jump-home")
        event.app.invalidate()

    @bindings.add("end")
    def _(event) -> None:  # type: ignore[override]
        _scroll_window(window, len(lines), len(lines))
        _sync_viewport_state_from_window()
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
            "redraw-check-digit": "bold reverse",
        }
    )

    application = Application(
        layout=Layout(root_container),
        key_bindings=bindings,
        full_screen=True,
        style=style,
    )
    # Remote/mobile terminals can deliver escape-sequence bytes with jitter.
    # Keep both parser and key-buffer flush timeouts long enough that cursor
    # key sequences are not split into stray characters.
    application.ttimeoutlen = 1.5
    application.timeoutlen = 1.5

    def _register_application_event(
        event_name: str, handler: Callable[[object], None]
    ) -> bool:
        event = getattr(application, event_name, None)
        if event is None:
            return False
        try:
            event += handler
        except Exception:
            return False
        return True

    def _position_redraw_check_digit(_app: object = None) -> None:
        if overlay_float is None:
            return
        # The float is screen-relative, so recompute it from live viewport
        # geometry before each render rather than caching a stale location.
        width = _window_width() or 0
        height = _window_height()
        overlay_float.left = max((width - 1) // 2, 0)
        overlay_float.top = max((height - 1) // 2, 0)

    def _advance_redraw_check_digit(app: object) -> None:
        nonlocal redraw_check_digit_counter
        if overlay_float is None:
            return
        renderer = getattr(app, "renderer", None)
        if getattr(renderer, "last_rendered_screen", None) is None:
            return
        # Advance after the frame is drawn so the digit visible on-screen
        # corresponds to the frame that was just rendered, not the next one.
        redraw_check_digit_counter = (redraw_check_digit_counter + 1) % 10

    if overlay_float is not None:
        _position_redraw_check_digit()
        _register_application_event("before_render", _position_redraw_check_digit)
        _register_application_event("after_render", _advance_redraw_check_digit)

    def _capture_timeout_framebuffer() -> Optional[Tuple[Path, Path]]:
        if automation_timeout_screenshot_basename is None:
            return None

        width = _window_width() or 0
        height = _window_height()
        safe_width = max(int(width), 1)
        safe_height = max(int(height), 1)

        captured_cells = _capture_prompt_toolkit_framebuffer(
            application,
            width=safe_width,
            height=safe_height,
        )
        capture_source = "prompt_toolkit-renderer"
        if captured_cells is None:
            # Fall back to a synthetic text-buffer capture when prompt_toolkit
            # does not expose a framebuffer. This keeps automation artifacts
            # available even in lean or partially mocked environments.
            capture_source = "synthetic-text-buffer"
            captured_cells = _capture_text_buffer_framebuffer(
                lines=lines,
                vertical_scroll=int(getattr(window, "vertical_scroll", 0)),
                horizontal_scroll=int(getattr(window, "horizontal_scroll", 0)),
                width=safe_width,
                height=safe_height,
            )

        return _write_timeout_framebuffer_capture(
            target_basename=automation_timeout_screenshot_basename,
            cell_rows=captured_cells,
            width=safe_width,
            height=safe_height,
            capture_source=capture_source,
            vertical_scroll=int(getattr(window, "vertical_scroll", 0)),
            horizontal_scroll=int(getattr(window, "horizontal_scroll", 0)),
            document_index=_active_document_index() + 1,
            document_count=max(document_count, 1),
        )

    scheduled_timers: List[threading.Timer] = []
    pre_run_replay_callbacks: List[Callable[[], None]] = []

    def _dispatch_on_event_loop(callback: Callable[[], None]) -> None:
        # Timer threads must hop onto the prompt_toolkit event loop before they
        # touch application state. During startup the executor hook may not be
        # ready yet, so keep the direct-call fallback for zero-delay flows.
        dispatcher = getattr(application, "call_from_executor", None)
        if callable(dispatcher):
            try:
                dispatcher(callback)
                return
            except RuntimeError:
                # prompt_toolkit may not have started an event loop yet.
                pass
        callback()

    if automation_replay:
        prepared_replay: List[Tuple[float, str, List[object]]] = []
        for event_index, (delay_seconds, key_spec) in enumerate(automation_replay):
            try:
                key_presses = _build_automation_key_presses(key_spec)
            except ValueError as error:
                raise RuntimeError(
                    "invalid automation key spec at index " f"{event_index}: {error}"
                ) from error
            prepared_replay.append(
                (max(float(delay_seconds), 0.0), key_spec, key_presses)
            )

        cumulative_delay = 0.0
        for event_index, (delay_seconds, key_spec, key_presses) in enumerate(
            prepared_replay
        ):
            cumulative_delay += delay_seconds

            def _inject_replay_event(
                *,
                replay_index: int = event_index,
                replay_spec: str = key_spec,
                replay_keys: List[object] = key_presses,
            ) -> None:
                if getattr(application, "is_done", False):
                    return
                key_processor = getattr(application, "key_processor", None)
                feed_multiple = getattr(key_processor, "feed_multiple", None)
                process_keys = getattr(key_processor, "process_keys", None)
                if not callable(feed_multiple) or not callable(process_keys):
                    _emit_ui_event(
                        "automation-replay-skipped",
                        index=replay_index,
                        key_spec=replay_spec,
                        reason="key-processor-unavailable",
                    )
                    return

                feed_multiple(list(replay_keys))
                process_keys()
                invalidator = getattr(application, "invalidate", None)
                if callable(invalidator):
                    invalidator()
                _emit_ui_event(
                    "automation-replay-key",
                    index=replay_index,
                    key_spec=replay_spec,
                    key_count=len(replay_keys),
                )

            if cumulative_delay == 0:
                # Zero-delay events still need the app to exist, so queue them
                # for the pre-run hook instead of firing them synchronously.
                pre_run_replay_callbacks.append(_inject_replay_event)
                continue

            replay_timer = threading.Timer(
                cumulative_delay,
                lambda callback=_inject_replay_event: _dispatch_on_event_loop(callback),
            )
            replay_timer.daemon = True
            replay_timer.start()
            scheduled_timers.append(replay_timer)

    if automation_timeout is not None:
        timeout_seconds = max(float(automation_timeout), 0.0)

        def _automation_quit() -> None:
            if getattr(application, "is_done", False):
                return
            if automation_timeout_screenshot_basename is not None:
                try:
                    screenshot_paths = _capture_timeout_framebuffer()
                except Exception as error:
                    _emit_ui_event(
                        "automation-timeout-screenshot-failed",
                        basename=str(automation_timeout_screenshot_basename),
                        error=str(error),
                    )
                else:
                    if screenshot_paths is not None:
                        txt_path, attrs_path = screenshot_paths
                        _emit_ui_event(
                            "automation-timeout-screenshot",
                            basename=str(automation_timeout_screenshot_basename),
                            txt_path=str(txt_path),
                            attrs_path=str(attrs_path),
                        )
            _emit_ui_event("automation-timeout", seconds=timeout_seconds)
            _request_quit(application)

        if timeout_seconds == 0:
            _automation_quit()
        else:
            timeout_timer = threading.Timer(
                timeout_seconds,
                lambda: _dispatch_on_event_loop(_automation_quit),
            )
            timeout_timer.daemon = True
            timeout_timer.start()
            scheduled_timers.append(timeout_timer)

    if pre_run_replay_callbacks:
        startup_delay_seconds = 0.05

        def _run_pre_run_replay_callbacks() -> None:
            # Give prompt_toolkit one small scheduling turn before injecting the
            # first replay event; this avoids races with startup rendering.
            for callback in list(pre_run_replay_callbacks):
                replay_timer = threading.Timer(
                    startup_delay_seconds,
                    lambda pending=callback: _dispatch_on_event_loop(pending),
                )
                replay_timer.daemon = True
                replay_timer.start()
                scheduled_timers.append(replay_timer)

        pre_run_callables = getattr(application, "pre_run_callables", None)
        if isinstance(pre_run_callables, list):
            pre_run_callables.append(_run_pre_run_replay_callbacks)
        else:
            _run_pre_run_replay_callbacks()

    try:
        application.run()
    except Exception as error:  # pragma: no cover - defensive fallback
        _add_fallback_notice(
            "prompt_toolkit pager failed: falling back to non-interactive "
            f"output. ({error})"
        )
        return False
    finally:
        for timer in scheduled_timers:
            timer.cancel()
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
    automation_timeout: Optional[float] = None,
    automation_replay: Optional[Sequence[AutomationReplayEvent]] = None,
    automation_timeout_screenshot_basename: Optional[Path] = None,
    viewport_columns: Optional[int] = None,
    viewport_rows: Optional[int] = None,
    redraw_check_digit: bool = False,
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
        automation_timeout: Optional max runtime in seconds before
            synthetic quit is injected for automation flows.
        automation_replay: Optional ordered replay events as
            `(delay_seconds, key_spec)` tuples.
        automation_timeout_screenshot_basename: Optional output basename for
            timeout framebuffer artifacts (`.txt` and `.attrs.json`).
        viewport_columns: Optional viewport width override for automation.
        viewport_rows: Optional viewport height override for automation.
        redraw_check_digit: When ``True``, overlay a center-screen check digit
            that advances on each interactive redraw.
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
        automation_timeout=automation_timeout,
        automation_replay=automation_replay,
        automation_timeout_screenshot_basename=automation_timeout_screenshot_basename,
        viewport_columns=viewport_columns,
        viewport_rows=viewport_rows,
        redraw_check_digit=redraw_check_digit,
    ):
        return
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()
