"""Hyperlink parsing and focus management utilities.

The helpers in this module keep hyperlink detection and navigation logic free
from UI dependencies so the interactive pager can reason about focus targets in
any terminal environment. Hyperlinks are detected conservatively using
Markdown-style ``[text](target)`` syntax to avoid false positives when the
rendered text originates from plain ANSI output.
"""

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


@dataclass(frozen=True)
class Hyperlink:
    """Represents a hyperlink anchored to a line and column span."""

    index: int
    line: int
    start: int
    end: int
    text: str
    target: str


def normalize_hyperlinks(
    lines: Sequence[str],
) -> Tuple[List[str], List[Hyperlink], Dict[int, List[Hyperlink]]]:
    """Return cleaned lines and hyperlink metadata extracted from Markdown links."""

    cleaned_lines: List[str] = []
    hyperlinks: List[Hyperlink] = []
    hyperlinks_by_line: Dict[int, List[Hyperlink]] = {}

    current_index = 0
    for line_number, line in enumerate(lines):
        cursor = 0
        rendered_fragments: List[str] = []
        line_links: List[Hyperlink] = []

        for match in _LINK_PATTERN.finditer(line):
            text, target = match.group(1), match.group(2)
            rendered_fragments.append(line[cursor : match.start()])
            start = sum(len(fragment) for fragment in rendered_fragments)
            end = start + len(text)
            line_links.append(
                Hyperlink(
                    index=current_index,
                    line=line_number,
                    start=start,
                    end=end,
                    text=text,
                    target=target,
                )
            )
            rendered_fragments.append(text)
            cursor = match.end()
            current_index += 1

        rendered_fragments.append(line[cursor:])
        cleaned_lines.append("".join(rendered_fragments))
        if line_links:
            hyperlinks_by_line[line_number] = line_links
            hyperlinks.extend(line_links)

    return cleaned_lines, hyperlinks, hyperlinks_by_line


def build_hyperlink_layout(lines: Sequence[str]) -> Dict[int, List[Hyperlink]]:
    """Return hyperlink spans keyed by line index with markup removed."""

    _, _, hyperlinks_by_line = normalize_hyperlinks(lines)
    return hyperlinks_by_line


class HyperlinkNavigator:
    """Track hyperlink focus with viewport-aware traversal semantics."""

    def __init__(self, hyperlinks: Iterable[Hyperlink]) -> None:
        self._hyperlinks: List[Hyperlink] = sorted(
            hyperlinks, key=lambda link: link.index
        )
        self._focus_index: Optional[int] = None

    @property
    def focus(self) -> Optional[Hyperlink]:
        if self._focus_index is None:
            return None
        return self._hyperlinks[self._focus_index]

    @property
    def hyperlinks(self) -> List[Hyperlink]:
        return list(self._hyperlinks)

    def _visible_indices(self, top: int, height: int) -> List[int]:
        bottom = top + max(height - 1, 0)
        return [
            index
            for index, link in enumerate(self._hyperlinks)
            if top <= link.line <= bottom
        ]

    def _midpoint_line(self, top: int, height: int) -> int:
        return top + max(height // 2, 0)

    def _focus_from_view(self, top: int, height: int) -> Optional[int]:
        visible = self._visible_indices(top, height)
        if not visible:
            return None

        midpoint = self._midpoint_line(top, height)
        after_midpoint = [
            index for index in visible if self._hyperlinks[index].line >= midpoint
        ]
        if after_midpoint:
            return after_midpoint[0]
        return visible[-1]

    def _advance_within(self, visible: List[int], step: int) -> Optional[int]:
        if not visible:
            return self._focus_index

        if self._focus_index in visible:
            position = visible.index(self._focus_index)
            return visible[(position + step) % len(visible)]

        return visible[0] if step > 0 else visible[-1]

    def focus_next(self, top: int, height: int) -> Optional[Hyperlink]:
        """Advance focus to the next visible hyperlink with wrap-around."""

        visible = self._visible_indices(top, height)
        if not visible:
            return self.focus

        candidate = self._focus_index
        if candidate is None or candidate not in visible:
            candidate = self._focus_from_view(top, height)
        else:
            candidate = self._advance_within(visible, step=1)

        self._focus_index = candidate
        return self.focus

    def focus_previous(self, top: int, height: int) -> Optional[Hyperlink]:
        """Move focus to the previous visible hyperlink with wrap-around."""

        visible = self._visible_indices(top, height)
        if not visible:
            return self.focus

        candidate = self._focus_index
        if candidate is None or candidate not in visible:
            candidate = self._focus_from_view(top, height)
        else:
            candidate = self._advance_within(visible, step=-1)

        self._focus_index = candidate
        return self.focus
