"""Viewport state model for mdview's internal dual-axis viewer engine."""

from dataclasses import dataclass
from typing import Tuple


def _clamp(value: int, lower: int, upper: int) -> int:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


@dataclass
class ViewportState:
    """Track viewport and virtual-document geometry for dual-axis navigation."""

    viewport_width: int
    viewport_height: int
    document_width: int
    document_height: int
    row_offset: int = 0
    column_offset: int = 0

    def __post_init__(self) -> None:
        self.viewport_width = max(1, self.viewport_width)
        self.viewport_height = max(1, self.viewport_height)
        self.document_width = max(0, self.document_width)
        self.document_height = max(0, self.document_height)
        self._clamp_offsets()

    @property
    def max_row_offset(self) -> int:
        """Return the largest valid vertical offset."""

        return max(self.document_height - self.viewport_height, 0)

    @property
    def max_column_offset(self) -> int:
        """Return the largest valid horizontal offset."""

        return max(self.document_width - self.viewport_width, 0)

    @property
    def horizontal_overflow_active(self) -> bool:
        """Return True when horizontal panning should be available."""

        return self.document_width > self.viewport_width

    @property
    def vertical_overflow_active(self) -> bool:
        """Return True when vertical scrolling should be available."""

        return self.document_height > self.viewport_height

    def _clamp_offsets(self) -> None:
        self.row_offset = _clamp(self.row_offset, 0, self.max_row_offset)
        self.column_offset = _clamp(self.column_offset, 0, self.max_column_offset)

    def set_document_size(self, width: int, height: int) -> None:
        """Update virtual document geometry and clamp offsets."""

        self.document_width = max(0, width)
        self.document_height = max(0, height)
        self._clamp_offsets()

    def resize_viewport(self, width: int, height: int) -> None:
        """Resize viewport geometry while preserving anchors where possible."""

        self.viewport_width = max(1, width)
        self.viewport_height = max(1, height)
        self._clamp_offsets()

    def pan_vertical(self, delta: int) -> int:
        """Move vertical offset by ``delta`` with bound clamping."""

        before = self.row_offset
        self.row_offset = _clamp(self.row_offset + delta, 0, self.max_row_offset)
        return self.row_offset - before

    def pan_horizontal(self, delta: int) -> int:
        """Move horizontal offset by ``delta`` with bound clamping."""

        before = self.column_offset
        self.column_offset = _clamp(
            self.column_offset + delta,
            0,
            self.max_column_offset,
        )
        return self.column_offset - before

    def visible_row_range(self) -> Tuple[int, int]:
        """Return the inclusive-exclusive visible row slice."""

        start = self.row_offset
        end = min(start + self.viewport_height, self.document_height)
        return start, end

    def visible_column_range(self) -> Tuple[int, int]:
        """Return the inclusive-exclusive visible column slice."""

        start = self.column_offset
        end = min(start + self.viewport_width, self.document_width)
        return start, end
