"""Utilities for resizing render targets and inspecting text framebuffers."""

import re
from typing import Callable, List, Optional, Sequence

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    """Return ``text`` with ANSI escape sequences removed."""

    return ANSI_ESCAPE.sub("", text)


class TextFramebuffer:
    """Represent rendered text as a coordinate-addressable framebuffer."""

    def __init__(self, rendered_text: str):
        self.rendered_text = rendered_text
        self.raw_lines: List[str] = rendered_text.splitlines()
        self.plain_lines: List[str] = [strip_ansi(line) for line in self.raw_lines]
        self.height: int = len(self.plain_lines)
        self.width: int = max((len(line) for line in self.plain_lines), default=0)

    def cell(self, row: int, column: int, default: str = " ") -> str:
        """Return the character at ``row`` and ``column`` or ``default``."""

        if row < 0 or column < 0 or row >= self.height:
            return default
        line = self.plain_lines[row]
        if column >= len(line):
            return default
        return line[column]

    def region(
        self, top: int, left: int, height: int, width: int, default: str = " "
    ) -> List[str]:
        """Return a rectangular slice of the framebuffer as plain-text rows."""

        rows: List[str] = []
        for row_index in range(top, top + height):
            row_chars = [
                self.cell(row_index, column_index, default)
                for column_index in range(left, left + width)
            ]
            rows.append("".join(row_chars))
        return rows

    def region_around(self, row: int, column: int, radius: int = 1) -> List[str]:
        """Return a square region centered on ``row``/``column``."""

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
        self.framebuffer: Optional[TextFramebuffer] = None

    def render(self, *, width: Optional[int] = None) -> TextFramebuffer:
        """Render content at ``width`` and store the framebuffer."""

        self.last_width = width
        rendered_text = self.renderer(
            self.content, markdown=self.markdown, width=width, **self.extra_kwargs
        )
        self.framebuffer = TextFramebuffer(rendered_text)
        return self.framebuffer

    def resize(self, width: int) -> TextFramebuffer:
        """Render using a new ``width`` and return the resulting framebuffer."""

        return self.render(width=width)


def find_line(lines: Sequence[str], predicate: Callable[[str], bool]) -> int:
    """Return the index of the first line matching ``predicate``."""

    for index, line in enumerate(lines):
        if predicate(line):
            return index
    raise AssertionError("expected line not found")
