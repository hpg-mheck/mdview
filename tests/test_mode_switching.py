from mdview.mode_switching import (
    ModeToggleState,
    SearchHighlight,
    ViewingMode,
    toggle_viewing_mode,
)


def test_toggle_enables_horizontal_and_restores_offset() -> None:
    state = ModeToggleState(
        mode=ViewingMode.WRAP,
        top_line=5,
        saved_horizontal_offset=12,
    )

    result = toggle_viewing_mode(state)

    assert result.state.mode is ViewingMode.HORIZONTAL
    assert result.state.horizontal_offset == 12
    assert result.state.top_line == 5
    assert "Horizontal scrolling enabled" in result.status_message


def test_toggle_to_wrap_clears_offset_and_saves_position() -> None:
    state = ModeToggleState(
        mode=ViewingMode.HORIZONTAL,
        top_line=10,
        horizontal_offset=22,
    )

    result = toggle_viewing_mode(state)

    assert result.state.mode is ViewingMode.WRAP
    assert result.state.horizontal_offset == 0
    assert result.state.saved_horizontal_offset == 22
    assert result.state.top_line == 10
    assert "Word wrap enabled" in result.status_message


def test_toggle_ignored_while_gesture_in_progress() -> None:
    state = ModeToggleState(mode=ViewingMode.HORIZONTAL, top_line=4)

    result = toggle_viewing_mode(state, gesture_in_progress=True)

    assert result.state == state
    assert "Ignored mode toggle" in result.status_message
    assert "ignored" in result.announcement


def test_toggle_disabled_when_wrapping_not_supported() -> None:
    state = ModeToggleState(mode=ViewingMode.WRAP)

    result = toggle_viewing_mode(state, wrap_supported=False)

    assert result.state == state
    assert "does not support wrapping" in result.status_message
    assert "Cannot toggle word wrap" in result.announcement


def test_toggle_aligns_search_highlight_visibility() -> None:
    state = ModeToggleState(
        mode=ViewingMode.WRAP,
        top_line=15,
        saved_horizontal_offset=0,
        search_highlight=SearchHighlight(line=20, column=120),
    )

    result = toggle_viewing_mode(state, viewport_width=80, viewport_height=3)

    assert result.state.mode is ViewingMode.HORIZONTAL
    assert result.state.horizontal_offset == 120
    assert result.state.top_line == 18
    assert result.match_visible is True
