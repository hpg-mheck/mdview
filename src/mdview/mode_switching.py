"""Mode switching utilities for toggling wrap and horizontal scroll modes.

The functions in this module are intentionally state-centric so they can be
used by interactive front ends without binding to a specific pager
implementation. Each toggle operation returns both user-facing status text and
screen-reader announcements to satisfy accessibility guidance while keeping the
core logic testable in isolation.
"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Tuple


class ViewingMode(str, Enum):
    """Supported viewing modes."""

    WRAP = "wrap"
    HORIZONTAL = "horizontal"


@dataclass(frozen=True)
class SearchHighlight:
    """Represents the active search match anchor within the document."""

    line: int
    column: int


@dataclass(frozen=True)
class ModeToggleState:
    """Captures the viewport state needed for safe mode transitions."""

    mode: ViewingMode = ViewingMode.WRAP
    top_line: int = 0
    horizontal_offset: int = 0
    saved_horizontal_offset: Optional[int] = None
    search_highlight: Optional[SearchHighlight] = None


@dataclass(frozen=True)
class ModeToggleResult:
    """Holds the new state and user messaging produced by a toggle."""

    state: ModeToggleState
    status_message: str
    announcement: str
    match_visible: bool


def toggle_viewing_mode(
    state: ModeToggleState,
    *,
    gesture_in_progress: bool = False,
    wrap_supported: bool = True,
    viewport_width: int = 80,
    viewport_height: Optional[int] = None,
) -> ModeToggleResult:
    """Toggle between wrap and horizontal modes while preserving context.

    The toggle honors kinetic scroll gestures by refusing to change modes until
    the gesture completes. For documents that cannot be wrapped, the toggle is
    disabled and emits a clear announcement instead of silently failing. When a
    toggle succeeds, the function restores the last known horizontal offset for
    the view, preserves the top logical line, and keeps the active search match
    in view.

    Args:
        state: The current viewport state.
        gesture_in_progress: When ``True``, the toggle is ignored to avoid
            fighting with ongoing scroll momentum.
        wrap_supported: When ``False``, disables the toggle entirely to respect
            non-wrappable renderers.
        viewport_width: Width of the visible region used to determine whether a
            search highlight remains visible during horizontal toggles.
        viewport_height: Optional viewport height used to align the top line to
            keep the search highlight in view when required.

    Returns:
        A :class:`ModeToggleResult` describing the new state along with status
        and accessibility messaging.
    """

    if gesture_in_progress:
        return ModeToggleResult(
            state=state,
            status_message=(
                "Ignored mode toggle while scrolling; try again after the "
                "gesture settles."
            ),
            announcement=(
                "Mode toggle ignored because scrolling is still in progress."
            ),
            match_visible=True,
        )

    if not wrap_supported:
        return ModeToggleResult(
            state=state,
            status_message=(
                "Mode toggle unavailable: this document does not support " "wrapping."
            ),
            announcement=(
                "Cannot toggle word wrap for this document. Wrapping is " "disabled."
            ),
            match_visible=True,
        )

    if state.mode is ViewingMode.WRAP:
        restored_offset = state.saved_horizontal_offset or 0
        top_line = state.top_line
        restored_offset = _ensure_match_visibility(
            state.search_highlight,
            restored_offset,
            viewport_width=viewport_width,
        )
        top_line, match_visible = _align_top_line(
            state.search_highlight,
            top_line,
            viewport_height=viewport_height,
        )
        new_state = replace(
            state,
            mode=ViewingMode.HORIZONTAL,
            horizontal_offset=restored_offset,
            top_line=top_line,
        )
        return ModeToggleResult(
            state=new_state,
            status_message=("Horizontal scrolling enabled. Word wrap is now disabled."),
            announcement=(
                "Horizontal scrolling on. Word wrap off. Search highlight " "preserved."
            ),
            match_visible=match_visible,
        )

    saved_offset = state.horizontal_offset or state.saved_horizontal_offset or 0
    cleared_offset = 0
    top_line, match_visible = _align_top_line(
        state.search_highlight,
        state.top_line,
        viewport_height=viewport_height,
    )
    new_state = replace(
        state,
        mode=ViewingMode.WRAP,
        saved_horizontal_offset=saved_offset,
        horizontal_offset=cleared_offset,
        top_line=top_line,
    )
    return ModeToggleResult(
        state=new_state,
        status_message=("Word wrap enabled. Horizontal offsets cleared."),
        announcement=(
            "Word wrap on. Horizontal scrolling reset. Search highlight " "preserved."
        ),
        match_visible=match_visible,
    )


def _ensure_match_visibility(
    highlight: Optional[SearchHighlight],
    offset: int,
    *,
    viewport_width: int,
) -> int:
    if highlight is None:
        return offset

    if viewport_width <= 0:
        return highlight.column

    visible_start = offset
    visible_end = offset + max(viewport_width - 1, 0)

    if highlight.column < visible_start:
        return highlight.column
    if highlight.column > visible_end:
        return highlight.column

    return offset


def _align_top_line(
    highlight: Optional[SearchHighlight],
    top_line: int,
    *,
    viewport_height: Optional[int],
) -> Tuple[int, bool]:
    if highlight is None or viewport_height is None or viewport_height <= 0:
        return top_line, True

    if highlight.line < top_line:
        return highlight.line, True

    if highlight.line >= top_line + viewport_height:
        return max(highlight.line - viewport_height + 1, 0), True

    return top_line, True


__all__ = [
    "ModeToggleResult",
    "ModeToggleState",
    "SearchHighlight",
    "ViewingMode",
    "toggle_viewing_mode",
]
