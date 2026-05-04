import importlib.util
from pathlib import Path

import pytest

import mdview.rendering as rendering_module
from mdview.intake import ingest_content
from mdview.rendering import _format_pipe_tables, render_to_ansi
from mdview.viewer import ViewerSession
from tests.helpers.framebuffer import RenderContainer, find_line, strip_ansi

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "resources" / "tests"
MARKDOWN_TABLE_FIXTURE_ROOT = FIXTURE_ROOT / "markdown" / "tables"


def test_table_formatter_preserves_header_body_alignment_cues() -> None:
    content = (FIXTURE_ROOT / "markdown_table_alignment.md").read_text(encoding="utf-8")
    formatted = _format_pipe_tables(content)
    lines = [strip_ansi(line) for line in formatted.splitlines()]

    assert lines[0].startswith("┌")
    assert "name" in lines[1]
    assert "score" in lines[1]
    assert "Ada Lovelace" in lines[3]
    assert "99" in lines[3]
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


def test_table_formatter_discards_span_color_wrappers_in_cells() -> None:
    content = (
        MARKDOWN_TABLE_FIXTURE_ROOT / "heading_followed_by_span_color_table.md"
    ).read_text(encoding="utf-8")

    formatted = _format_pipe_tables(content)

    assert "<span" not in formatted.lower()
    assert "</span>" not in formatted.lower()
    assert "alpha" in formatted
    assert "beta" in formatted


def test_render_to_ansi_applies_span_cell_colors() -> None:
    content = (
        MARKDOWN_TABLE_FIXTURE_ROOT / "heading_followed_by_span_color_table.md"
    ).read_text(encoding="utf-8")

    rendered = render_to_ansi(content, markdown=True, width=80)

    assert "\x1b[38;2;128;128;128m┌" in rendered
    assert "\x1b[38;2;255;0;0m" in rendered
    assert "\x1b[38;2;0;0;255m" in rendered
    assert "alpha" in rendered
    assert "beta" in rendered


def test_table_formatter_honors_no_table_borders() -> None:
    content = (FIXTURE_ROOT / "markdown_table_alignment.md").read_text(encoding="utf-8")

    formatted = _format_pipe_tables(content, table_borders=False)
    plain = strip_ansi(formatted)

    assert "┌" not in plain
    assert "┐" not in plain
    assert "└" not in plain
    assert "┘" not in plain
    assert "│" in plain
    assert "┼" in plain


def test_table_formatter_honors_no_cell_borders() -> None:
    content = (FIXTURE_ROOT / "markdown_table_alignment.md").read_text(encoding="utf-8")

    formatted = _format_pipe_tables(content, cell_borders=False)
    plain = strip_ansi(formatted)

    assert "┌" in plain
    assert "└" in plain
    assert "┬" not in plain
    assert "┼" not in plain
    assert plain.count("│") == 8


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
    lines = [strip_ansi(line) for line in formatted.splitlines()]

    assert len(lines) == 5
    assert "abcdefghijklmnop" in formatted
    assert lines[0].startswith("┌")
    assert "abcdefghijklmnop" in lines[3]


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

    if rendering_module.HAS_RICH:

        def _spy_table_renderer(
            console: object,
            text: str,
            *,
            viewport_width=None,
            readability_first_tables=False,
            table_borders=True,
            cell_borders=True,
        ) -> None:
            calls.append(
                {
                    "viewport_width": viewport_width,
                    "readability_first_tables": readability_first_tables,
                    "table_borders": table_borders,
                    "cell_borders": cell_borders,
                }
            )

        monkeypatch.setattr(
            rendering_module,
            "_render_rich_markdown_with_custom_tables",
            _spy_table_renderer,
        )
    else:

        def _spy_table_formatter(
            text: str,
            *,
            viewport_width=None,
            readability_first_tables=False,
            table_borders=True,
            cell_borders=True,
        ):
            calls.append(
                {
                    "viewport_width": viewport_width,
                    "readability_first_tables": readability_first_tables,
                    "table_borders": table_borders,
                    "cell_borders": cell_borders,
                }
            )
            return text

        monkeypatch.setattr(
            rendering_module, "_format_pipe_tables", _spy_table_formatter
        )

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
    assert calls[0]["table_borders"] is True
    assert calls[0]["cell_borders"] is True
    assert calls[1]["viewport_width"] == 18
    assert calls[1]["readability_first_tables"] is True
    assert calls[1]["table_borders"] is True
    assert calls[1]["cell_borders"] is True


@pytest.mark.skipif(
    importlib.util.find_spec("rich") is None, reason="rich is required for this test"
)
def test_heading_to_table_gap_matches_for_plain_and_span_color_tables() -> None:
    plain_content = (
        MARKDOWN_TABLE_FIXTURE_ROOT / "heading_followed_by_plain_table.md"
    ).read_text(encoding="utf-8")
    span_content = (
        MARKDOWN_TABLE_FIXTURE_ROOT / "heading_followed_by_span_color_table.md"
    ).read_text(encoding="utf-8")

    plain = RenderContainer(render_to_ansi, plain_content, markdown=True).render(
        width=80, height=12
    )
    span = RenderContainer(render_to_ansi, span_content, markdown=True).render(
        width=80, height=12
    )

    plain_heading = find_line(
        plain.plain_lines, lambda line: "Table Gap Heading" in line
    )
    span_heading = find_line(span.plain_lines, lambda line: "Table Gap Heading" in line)
    plain_table = find_line(plain.plain_lines, lambda line: "┌" in line and "┐" in line)
    span_table = find_line(span.plain_lines, lambda line: "┌" in line and "┐" in line)
    plain_header_row = find_line(
        plain.plain_lines, lambda line: "Metric" in line and "Value" in line
    )
    span_header_row = find_line(
        span.plain_lines, lambda line: "Metric" in line and "Value" in line
    )

    plain_gap = plain_table - plain_heading - 1
    span_gap = span_table - span_heading - 1

    assert plain_gap > 0
    assert span_gap == plain_gap
    assert all(
        not line.strip() for line in plain.plain_lines[plain_heading + 1 : plain_table]
    )
    assert all(
        not line.strip() for line in span.plain_lines[span_heading + 1 : span_table]
    )
    assert plain_header_row == plain_table + 1
    assert span_header_row == span_table + 1
