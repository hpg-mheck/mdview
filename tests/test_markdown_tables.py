from pathlib import Path

import mdview.rendering as rendering_module
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


def test_auto_table_profile_uses_fit_first_when_it_can_fit() -> None:
    content = "\n".join(
        [
            "| k | value |",
            "| :--- | :--- |",
            "| A | abcdefghijklmnop |",
            "",
        ]
    )

    formatted = _format_pipe_tables(content, viewport_width=18)
    lines = formatted.splitlines()

    assert len(lines) > 3
    assert "abcdefghijklmnop" not in formatted


def test_readability_first_flag_keeps_unbroken_wide_cell_content() -> None:
    content = "\n".join(
        [
            "| k | value |",
            "| :--- | :--- |",
            "| A | abcdefghijklmnop |",
            "",
        ]
    )

    formatted = _format_pipe_tables(
        content,
        viewport_width=18,
        readability_first_tables=True,
    )
    lines = formatted.splitlines()

    assert len(lines) == 3
    assert "abcdefghijklmnop" in formatted


def test_auto_profile_falls_back_to_readability_when_fit_cannot_avoid_overflow() -> (
    None
):
    content = "\n".join(
        [
            "| c1 | c2 | c3 | c4 | c5 | c6 |",
            "| :-- | :-- | :-- | :-- | :-- | :-- |",
            "| a | b | c | d | e | abcdefghijklmnop |",
            "",
        ]
    )

    formatted = _format_pipe_tables(content, viewport_width=20)

    assert "abcdefghijklmnop" in formatted


def test_render_to_ansi_honors_readability_first_table_flag(monkeypatch) -> None:
    calls = []

    def _spy_table_formatter(
        text: str,
        *,
        viewport_width=None,
        readability_first_tables=False,
    ):
        calls.append(
            {
                "viewport_width": viewport_width,
                "readability_first_tables": readability_first_tables,
            }
        )
        return text

    monkeypatch.setattr(rendering_module, "_format_pipe_tables", _spy_table_formatter)

    content = "\n".join(
        [
            "| k | value |",
            "| :--- | :--- |",
            "| A | abcdefghijklmnop |",
            "",
        ]
    )

    render_to_ansi(content, markdown=True, width=18)
    render_to_ansi(
        content,
        markdown=True,
        width=18,
        readability_first_tables=True,
    )

    assert calls[0]["viewport_width"] == 18
    assert calls[0]["readability_first_tables"] is False
    assert calls[1]["viewport_width"] == 18
    assert calls[1]["readability_first_tables"] is True
