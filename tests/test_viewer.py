from pathlib import Path

from mdview.dom import Block, ConstraintProfile, Line, StyleProfile
from mdview.intake import ingest_content
from mdview.viewer import ViewerSession, block_reflowable

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "resources" / "tests"


def test_block_reflowable_hard_limit_overrides_mode_and_hints() -> None:
    block = Block(
        block_id="b1",
        lines=(Line.from_source("wide table row"),),
        constraints=ConstraintProfile(no_reflow=True, wrap_hint="prose"),
        style=StyleProfile(block_type="prose"),
    )

    assert block_reflowable(block, "all") is False
    assert block_reflowable(block, "prose") is False


def test_block_reflowable_consumes_soft_hints_in_prose_mode() -> None:
    block = Block(
        block_id="b1",
        lines=(Line.from_source("candidate line"),),
        constraints=ConstraintProfile(no_reflow=False, wrap_hint="prose"),
        style=StyleProfile(block_type="list_like"),
    )

    assert block_reflowable(block, "prose") is True
    assert block_reflowable(block, "none") is False


def test_viewer_session_activates_horizontal_scroll_for_wide_literal_table() -> None:
    content = (FIXTURE_ROOT / "wide_literal_table.txt").read_text(encoding="utf-8")
    document = ingest_content(content, markdown=False)
    session = ViewerSession.from_document(
        document=document,
        reflow_mode="none",
        viewport_width=40,
        viewport_height=5,
    )

    assert session.horizontal_scrollbar_active is True
    before = session.viewport.column_offset
    moved = session.pan_right(7)
    assert moved > 0
    assert session.viewport.column_offset > before
    session.pan_left(999)
    assert session.viewport.column_offset == 0


def test_viewer_session_keeps_wide_markdown_table_overflow_pannable() -> None:
    content = (FIXTURE_ROOT / "wide_markdown_table.md").read_text(encoding="utf-8")
    document = ingest_content(content, markdown=True)
    session = ViewerSession.from_document(
        document=document,
        reflow_mode="none",
        viewport_width=30,
        viewport_height=4,
    )

    assert session.horizontal_scrollbar_active is True
    initial = list(session.visible_lines())
    session.pan_right(10)
    shifted = list(session.visible_lines())
    assert shifted != initial


def test_viewer_resize_preserves_anchor_when_possible() -> None:
    content = (FIXTURE_ROOT / "wide_literal_table.txt").read_text(encoding="utf-8")
    document = ingest_content(content, markdown=False)
    session = ViewerSession.from_document(
        document=document,
        reflow_mode="none",
        viewport_width=45,
        viewport_height=4,
    )
    session.pan_right(8)
    session.pan_down(1)
    row_before = session.viewport.row_offset
    col_before = session.viewport.column_offset

    session.resize(viewport_width=35, viewport_height=3)
    assert session.viewport.row_offset == row_before
    assert session.viewport.column_offset == col_before
