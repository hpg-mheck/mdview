from pathlib import Path

from mdview.intake import ingest_content
from mdview.rendering import _format_pipe_tables, render_to_ansi
from mdview.viewer import ViewerSession


FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "resources" / "tests"


def test_table_formatter_preserves_header_body_alignment_cues() -> None:
    content = (FIXTURE_ROOT / "markdown_table_alignment.md").read_text(encoding="utf-8")
    formatted = _format_pipe_tables(content)
    lines = formatted.splitlines()

    assert lines[0].startswith("| name")
    assert "| :----------- | ----: | :---: |" in lines[1]
    assert "| Ada Lovelace |    99 |" in lines[2]
    assert "Outside table paragraph." in formatted


def test_wide_markdown_table_enables_horizontal_overflow_in_viewer() -> None:
    content = (FIXTURE_ROOT / "wide_markdown_table.md").read_text(encoding="utf-8")
    document = ingest_content(content, markdown=True)
    session = ViewerSession.from_document(
        document=document,
        reflow_mode="none",
        viewport_width=25,
        viewport_height=4,
    )

    assert session.horizontal_scrollbar_active is True
    before = list(session.visible_lines())
    session.pan_right(6)
    after = list(session.visible_lines())
    assert before != after


def test_render_to_ansi_keeps_fenced_content_literal_when_table_present() -> None:
    content = (FIXTURE_ROOT / "markdown_table_alignment.md").read_text(encoding="utf-8")
    rendered = render_to_ansi(content, markdown=True)

    assert "| not | a | table |" in rendered
    assert "| --- | --- | --- |" in rendered
