from mdview.viewport import ViewportState


def test_viewport_state_clamps_offsets_to_bounds() -> None:
    state = ViewportState(
        viewport_width=40,
        viewport_height=10,
        document_width=120,
        document_height=50,
        row_offset=999,
        column_offset=999,
    )

    assert state.max_row_offset == 40
    assert state.max_column_offset == 80
    assert state.row_offset == 40
    assert state.column_offset == 80


def test_viewport_panning_is_bounded_both_directions() -> None:
    state = ViewportState(
        viewport_width=20,
        viewport_height=5,
        document_width=60,
        document_height=30,
    )

    assert state.pan_horizontal(7) == 7
    assert state.column_offset == 7
    assert state.pan_horizontal(100) == 33
    assert state.column_offset == 40
    assert state.pan_horizontal(-100) == -40
    assert state.column_offset == 0

    assert state.pan_vertical(2) == 2
    assert state.row_offset == 2
    assert state.pan_vertical(100) == 23
    assert state.row_offset == 25
    assert state.pan_vertical(-100) == -25
    assert state.row_offset == 0


def test_overflow_flags_follow_document_and_viewport_dimensions() -> None:
    state = ViewportState(
        viewport_width=80,
        viewport_height=24,
        document_width=80,
        document_height=24,
    )
    assert state.horizontal_overflow_active is False
    assert state.vertical_overflow_active is False

    state.set_document_size(width=120, height=24)
    assert state.horizontal_overflow_active is True
    assert state.vertical_overflow_active is False

    state.set_document_size(width=120, height=60)
    assert state.horizontal_overflow_active is True
    assert state.vertical_overflow_active is True


def test_resize_preserves_anchor_when_still_in_bounds() -> None:
    state = ViewportState(
        viewport_width=50,
        viewport_height=12,
        document_width=120,
        document_height=80,
        row_offset=18,
        column_offset=22,
    )

    state.resize_viewport(width=40, height=10)
    assert state.row_offset == 18
    assert state.column_offset == 22

    state.resize_viewport(width=200, height=100)
    assert state.row_offset == 0
    assert state.column_offset == 0


def test_visible_ranges_reflect_offsets_and_geometry() -> None:
    state = ViewportState(
        viewport_width=15,
        viewport_height=4,
        document_width=40,
        document_height=11,
        row_offset=7,
        column_offset=30,
    )

    assert state.visible_row_range() == (7, 11)
    assert state.visible_column_range() == (25, 40)
