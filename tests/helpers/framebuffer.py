"""Utilities for resizing render targets and inspecting text framebuffers."""

import re
from typing import Callable, List, Optional, Sequence

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    """Return ``text`` with ANSI escape sequences removed."""

    return ANSI_ESCAPE.sub("", text)


class TextFramebuffer:
    """Represent rendered text as a coordinate-addressable framebuffer."""

    def __init__(
        self,
        rendered_text: str,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ):
        self.rendered_text = rendered_text
        self.raw_lines: List[str] = rendered_text.splitlines()
        self.plain_lines: List[str] = [strip_ansi(line) for line in self.raw_lines]

        computed_width = max((len(line) for line in self.plain_lines), default=0)
        computed_height = len(self.plain_lines)

        self.width: int = width if width is not None else computed_width
        self.height: int = height if height is not None else computed_height

        viewport_lines = [
            self._normalize_line_length(line, self.width) for line in self.plain_lines
        ]
        viewport_lines = self._pad_or_trim_height(viewport_lines)
        self._viewport_lines = viewport_lines

    def _normalize_line_length(self, line: str, width: int) -> str:
        if width <= 0:
            return ""
        if len(line) < width:
            return line.ljust(width)
        return line[:width]

    def _pad_or_trim_height(self, lines: List[str]) -> List[str]:
        if self.height <= 0:
            return []
        if len(lines) < self.height:
            padding = [" " * self.width for _ in range(self.height - len(lines))]
            return lines + padding
        return lines[: self.height]

    def peek(self, column: int, row: int, default: str = " ") -> str:
        """Return the character at ``column``/``row`` or ``default``.

        Coordinates are zero-based with (0, 0) at the upper-left corner of the
        viewport. ``column`` maps to the x-axis and ``row`` maps to the y-axis.
        """

        if row < 0 or column < 0 or row >= self.height:
            return default
        if row >= len(self._viewport_lines):
            return default
        line = self._viewport_lines[row]
        if column >= len(line):
            return default
        return line[column]

    def cell(self, column: int, row: int, default: str = " ") -> str:
        """Backward-compatible alias for :meth:`peek`."""

        return self.peek(column, row, default)

    def poke(self, column: int, row: int, value: str) -> None:
        """Write ``value`` into the viewport if coordinates are in range."""

        if len(value) != 1:
            raise ValueError("poke requires a single-character string")
        if self.width <= 0 or self.height <= 0:
            return
        if row < 0 or column < 0:
            return
        if row >= self.height or column >= self.width:
            return
        if row >= len(self._viewport_lines):
            return

        line = self._normalize_line_length(self._viewport_lines[row], self.width)
        characters = list(line)
        characters[column] = value
        self._viewport_lines[row] = "".join(characters)

    def region(
        self, top: int, left: int, height: int, width: int, default: str = " "
    ) -> List[str]:
        """Return a rectangular slice of the framebuffer as plain-text rows."""

        rows: List[str] = []
        for row_index in range(top, top + height):
            row_chars = [
                self.cell(column_index, row_index, default)
                for column_index in range(left, left + width)
            ]
            rows.append("".join(row_chars))
        return rows

    def region_around(self, column: int, row: int, radius: int = 1) -> List[str]:
        """Return a square region centered on ``column``/``row``."""

        size = radius * 2 + 1
        return self.region(row - radius, column - radius, size, size)


class RenderContainer:
    """Reusable render target that supports resizes and framebuffer capture."""

    def __init__(
        self,
        renderer: Callable[..., str],
        content: str,
        *,
        markdown: bool = True,
        extra_kwargs: Optional[Sequence[tuple]] = None,
    ) -> None:
        self.renderer = renderer
        self.content = content
        self.markdown = markdown
        self.extra_kwargs = dict(extra_kwargs or [])
        self.last_width: Optional[int] = None
        self.last_height: Optional[int] = None
        self.framebuffer: Optional[TextFramebuffer] = None

    def render(
        self, *, width: Optional[int] = None, height: Optional[int] = None
    ) -> TextFramebuffer:
        """Render content at ``width``/``height`` and store the framebuffer."""

        self.last_width = width
        self.last_height = height
        rendered_text = self.renderer(
            self.content,
            markdown=self.markdown,
            width=width,
            height=height,
            **self.extra_kwargs,
        )
        self.framebuffer = TextFramebuffer(rendered_text, width=width, height=height)
        return self.framebuffer

    def resize(self, width: int, height: int) -> TextFramebuffer:
        """Render using new dimensions and return the resulting framebuffer."""

        return self.render(width=width, height=height)


def find_line(lines: Sequence[str], predicate: Callable[[str], bool]) -> int:
    """Return the index of the first line matching ``predicate``."""

    for index, line in enumerate(lines):
        if predicate(line):
            return index
    raise AssertionError("expected line not found")
