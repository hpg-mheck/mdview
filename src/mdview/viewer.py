"""Policy-aware viewer helpers built on top of the internal DOM."""

from dataclasses import dataclass
import textwrap
from typing import List, Sequence

from mdview.dom import Block, Document
from mdview.viewport import ViewportState


def block_reflowable(block: Block, reflow_mode: str) -> bool:
    """Return whether a block is eligible for reflow in the active mode."""

    if reflow_mode == "none":
        return False
    if block.constraints.no_reflow:
        return False
    if reflow_mode == "all":
        return True
    if block.constraints.wrap_hint == "none":
        return False
    if block.style.block_type == "prose":
        return True
    return block.constraints.wrap_hint == "prose"


def materialize_plain_text_lines(
    *,
    document: Document,
    reflow_mode: str,
    width: int,
) -> List[str]:
    """Materialize a document into display lines under the active policy."""

    lines: List[str] = []
    target_width = max(1, width)

    for index, block in enumerate(document.blocks):
        if block_reflowable(block, reflow_mode):
            paragraph = " ".join(
                line.source_text.strip()
                for line in block.lines
                if line.source_text.strip()
            )
            if paragraph:
                lines.extend(
                    textwrap.wrap(
                        paragraph,
                        width=target_width,
                        break_long_words=False,
                        break_on_hyphens=False,
                    )
                )
            else:
                lines.append("")
        else:
            lines.extend(line.source_text for line in block.lines)

        if index < len(document.blocks) - 1:
            lines.append("")

    return lines


@dataclass
class ViewerSession:
    """Internal dual-axis viewer state tied to an ingested document."""

    document: Document
    reflow_mode: str
    viewport: ViewportState
    lines: List[str]

    @classmethod
    def from_document(
        cls,
        *,
        document: Document,
        reflow_mode: str,
        viewport_width: int,
        viewport_height: int,
    ) -> "ViewerSession":
        lines = materialize_plain_text_lines(
            document=document,
            reflow_mode=reflow_mode,
            width=viewport_width if reflow_mode != "none" else 10_000,
        )
        max_width = max((len(line) for line in lines), default=0)
        viewport = ViewportState(
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            document_width=max_width,
            document_height=len(lines),
        )
        return cls(
            document=document,
            reflow_mode=reflow_mode,
            viewport=viewport,
            lines=lines,
        )

    def resize(self, *, viewport_width: int, viewport_height: int) -> None:
        self.viewport.resize_viewport(viewport_width, viewport_height)

    def pan_left(self, amount: int = 1) -> int:
        return self.viewport.pan_horizontal(-abs(amount))

    def pan_right(self, amount: int = 1) -> int:
        return self.viewport.pan_horizontal(abs(amount))

    def pan_up(self, amount: int = 1) -> int:
        return self.viewport.pan_vertical(-abs(amount))

    def pan_down(self, amount: int = 1) -> int:
        return self.viewport.pan_vertical(abs(amount))

    @property
    def horizontal_scrollbar_active(self) -> bool:
        return self.viewport.horizontal_overflow_active

    def visible_lines(self) -> Sequence[str]:
        row_start, row_end = self.viewport.visible_row_range()
        col_start, col_end = self.viewport.visible_column_range()
        visible = self.lines[row_start:row_end]
        return [line[col_start:col_end] for line in visible]
