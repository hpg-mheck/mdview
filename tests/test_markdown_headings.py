"""Tests for Markdown heading rendering behavior."""

import importlib
import importlib.util
import re
from pathlib import Path
from typing import Callable, List, Tuple

import pytest

import mdview.rendering as rendering

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "tests"
    / "markdown"
    / "headings"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def _find_line(lines: List[str], predicate: Callable[[str], bool]) -> int:
    for index, line in enumerate(lines):
        if predicate(line):
            return index
    raise AssertionError("expected line not found")


@pytest.fixture
def render_heading(monkeypatch):
    def _render(
        filename: str,
        *,
        force_plain: bool = False,
        mixed_endings: bool = False,
    ) -> Tuple[List[str], List[str], str]:
        path = FIXTURE_DIR / filename
        content = path.read_text(encoding="utf-8")
        if mixed_endings:
            content = content.replace("\n", "\r\n")

        module = rendering
        if force_plain:
            original_find_spec = importlib.util.find_spec
            monkeypatch.setattr(
                importlib.util,
                "find_spec",
                lambda name: None if name == "rich" else original_find_spec(name),
            )
            module = importlib.reload(rendering)

        try:
            rendered = module.render_to_ansi(content, markdown=True)
            raw_lines = rendered.splitlines()
            cleaned = [_strip_ansi(line) for line in raw_lines]
        finally:
            if force_plain:
                monkeypatch.undo()
                importlib.reload(rendering)

        return cleaned, raw_lines, rendered

    return _render


@pytest.mark.parametrize("force_plain", [False, True])
def test_headings_preserve_hierarchy_and_spacing(
    render_heading, force_plain: bool
) -> None:
    cleaned, _, rendered = render_heading("h1_and_h2.md", force_plain=force_plain)

    first_index = _find_line(cleaned, lambda line: "Level One Heading" in line)
    second_index = _find_line(cleaned, lambda line: "Level Two Heading" in line)

    assert second_index > first_index
    assert any(not line.strip() for line in cleaned[first_index + 1 : second_index])
    assert rendered.endswith("\n")


@pytest.mark.parametrize("force_plain", [False, True])
def test_heading_levels_remain_distinct(render_heading, force_plain: bool) -> None:
    cleaned, _, _ = render_heading("h3_through_h6.md", force_plain=force_plain)

    texts = [
        "Tertiary Heading",
        "Quaternary Heading",
        "Quinary Heading",
        "Senary Heading",
    ]
    positions = [
        _find_line(cleaned, lambda line, text=text: text in line) for text in texts
    ]

    assert positions == sorted(positions)
    assert len(set(positions)) == len(texts)


@pytest.mark.parametrize("force_plain", [False, True])
def test_heading_punctuation_remains_literal(render_heading, force_plain: bool) -> None:
    cleaned, _, _ = render_heading(
        "heading_with_inline_punctuation.md", force_plain=force_plain
    )

    assert any(
        "Heading, with commas, periods, and a trailing colon:" in line
        for line in cleaned
    )


@pytest.mark.parametrize("force_plain", [False, True])
def test_heading_does_not_absorb_adjacent_text(
    render_heading, force_plain: bool
) -> None:
    cleaned, _, rendered = render_heading(
        "heading_adjacent_text.md", force_plain=force_plain
    )

    heading_index = _find_line(cleaned, lambda line: "Heading Beside Body" in line)
    body_index = _find_line(
        cleaned,
        lambda line: line.strip() == "This paragraph starts right after the heading.",
    )

    assert body_index > heading_index
    assert rendered.endswith("\n")


@pytest.mark.parametrize("force_plain", [False, True])
def test_inline_formatting_stays_within_heading(
    render_heading, force_plain: bool
) -> None:
    cleaned, raw_lines, _ = render_heading(
        "heading_with_inline_formatting.md", force_plain=force_plain
    )

    heading_index = _find_line(
        cleaned, lambda line: "Heading with" in line and "italic" in line
    )
    body_index = _find_line(
        cleaned,
        lambda line: line.strip()
        == "Plain continuation text that should stay unstyled.",
    )

    assert body_index > heading_index
    assert "italic" in cleaned[heading_index]
    assert "bold" in cleaned[heading_index]
    assert "\x1b" not in raw_lines[body_index]


def test_mixed_line_endings_match_native_output(render_heading) -> None:
    unix_cleaned, _, _ = render_heading("h1_and_h2.md")
    mixed_cleaned, _, _ = render_heading("h1_and_h2.md", mixed_endings=True)

    assert unix_cleaned == mixed_cleaned


def test_indented_hash_prefix_renders_as_literal(monkeypatch) -> None:
    content = (FIXTURE_DIR / "indented_heading_marker.md").read_text(encoding="utf-8")

    original_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: None if name == "rich" else original_find_spec(name),
    )
    plain_rendering = importlib.reload(rendering)
    plain_output = plain_rendering.render_to_ansi(content, markdown=True)

    monkeypatch.undo()
    rich_rendering = importlib.reload(rendering)
    rich_output = rich_rendering.render_to_ansi(content, markdown=True)

    for output in (plain_output, rich_output):
        lines = output.splitlines()
        assert any(line.strip() == "# Not a heading" for line in lines)
        assert not any("┏" in line or "┗" in line for line in lines)


def test_empty_heading_becomes_blank_line(render_heading) -> None:
    cleaned, raw_lines, rendered = render_heading("empty_heading.md")

    assert cleaned[0] == ""
    assert cleaned[1].strip() == "Following text after the empty heading."
    assert "\x1b" not in raw_lines[0]
    assert rendered.endswith("\n")


@pytest.mark.skipif(
    importlib.util.find_spec("rich") is None, reason="rich is required for this test"
)
def test_h1_panel_resizes_with_console_width(monkeypatch) -> None:
    """Heading panels should shrink to avoid border wrapping."""

    class NarrowConsole(rendering.Console):
        def __init__(self, *args, **kwargs):
            kwargs["width"] = 30
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(rendering, "Console", NarrowConsole)

    rendered = rendering.render_to_ansi(
        "# A very long heading title that exceeds width\n", markdown=True
    )
    heading_lines = [
        _strip_ansi(line)
        for line in rendered.splitlines()
        if line.startswith(("┏", "┃", "┗"))
    ]

    assert heading_lines
    assert all(len(line) <= 30 for line in heading_lines)
    assert len({len(line) for line in heading_lines}) == 1
    assert any("exceeds width" in line for line in heading_lines)


@pytest.mark.skipif(
    importlib.util.find_spec("rich") is None, reason="rich is required for this test"
)
def test_h1_panel_expands_to_console_width() -> None:
    rendered = rendering.render_to_ansi("# Expanded Title\n", markdown=True, width=48)
    frame_widths = {
        len(_strip_ansi(line))
        for line in rendered.splitlines()
        if line.startswith(("┏", "┗"))
    }

    assert frame_widths == {48}


@pytest.mark.skipif(
    importlib.util.find_spec("rich") is None, reason="rich is required for this test"
)
def test_h1_panel_recomputes_width_on_resize() -> None:
    narrow = rendering.render_to_ansi("# Expanding Title\n", markdown=True, width=32)
    wide = rendering.render_to_ansi("# Expanding Title\n", markdown=True, width=68)

    narrow_widths = {
        len(_strip_ansi(line))
        for line in narrow.splitlines()
        if line.startswith(("┏", "┗"))
    }
    wide_widths = {
        len(_strip_ansi(line))
        for line in wide.splitlines()
        if line.startswith(("┏", "┗"))
    }

    assert narrow_widths == {32}
    assert wide_widths == {68}
