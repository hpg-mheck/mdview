"""Tests for Markdown ordered list rendering behavior."""

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
    / "lists"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def _find_line(lines: List[str], predicate: Callable[[str], bool]) -> int:
    for index, line in enumerate(lines):
        if predicate(line):
            return index
    raise AssertionError("expected line not found")


def _leading_whitespace(line: str) -> int:
    return len(line) - len(line.lstrip())


def _text_column(line: str) -> int:
    match = re.match(r"(\s*\d+\.?\s)", line)
    if not match:
        raise AssertionError("expected numeric prefix")
    return len(match.group(1))


@pytest.fixture
def render_ordered(monkeypatch):
    def _render(
        filename: str, *, force_plain: bool = False
    ) -> Tuple[List[str], List[str], bool]:
        path = FIXTURE_DIR / filename
        content = path.read_text(encoding="utf-8")

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
            has_rich = module.HAS_RICH
        finally:
            if force_plain:
                monkeypatch.undo()
                importlib.reload(rendering)

        return cleaned, raw_lines, has_rich

    return _render


@pytest.mark.parametrize("force_plain", [False, True])
def test_incrementing_list_preserves_numbers_and_spacing(
    render_ordered, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich = render_ordered(
        "ordered_incrementing.md", force_plain=force_plain
    )

    before_index = _find_line(
        cleaned,
        lambda line: "Opening paragraph before the incrementing list." in line,
    )
    first_index = _find_line(
        cleaned, lambda line: "First item keeps the authored numbering" in line
    )
    middle_index = _find_line(
        cleaned, lambda line: "Second item continues the sequence" in line
    )
    last_index = _find_line(cleaned, lambda line: "Third item ends the list" in line)
    after_index = _find_line(
        cleaned,
        lambda line: "Closing paragraph after the incrementing list ends." in line,
    )

    assert before_index < first_index < middle_index < last_index < after_index
    assert not cleaned[first_index - 1].strip()
    assert not cleaned[last_index + 1].strip()

    digits = []
    for line in cleaned[first_index : last_index + 1]:
        match = re.match(r"\s*(\d+)", line)
        assert match
        digits.append(match.group(1))
    assert digits == ["1", "2", "3"]

    emphasis_line = cleaned[middle_index]
    if force_plain:
        assert "*emphasis*" in emphasis_line
    else:
        assert has_rich
        assert "emphasis" in emphasis_line
        assert "*" not in emphasis_line
        assert any(
            "\x1b" in line for line in raw_lines[middle_index : middle_index + 1]
        )


@pytest.mark.parametrize("force_plain", [False, True])
def test_offset_start_retains_authored_numbering(
    render_ordered, force_plain: bool
) -> None:
    cleaned, _, has_rich = render_ordered(
        "ordered_offset_start.md", force_plain=force_plain
    )

    first_index = _find_line(
        cleaned, lambda line: "Offset numbering begins at three" in line
    )
    second_index = _find_line(
        cleaned, lambda line: "Next item aligns with the offset" in line
    )

    assert re.match(r"\s*3\.?(?:\s|$)", cleaned[first_index])
    assert re.match(r"\s*4\.?(?:\s|$)", cleaned[second_index])
    if not force_plain:
        assert has_rich


@pytest.mark.parametrize("force_plain", [False, True])
def test_wrapped_lines_align_under_text_column(
    render_ordered, force_plain: bool
) -> None:
    cleaned, _, has_rich = render_ordered(
        "ordered_wrapped_items.md", force_plain=force_plain
    )

    first_index = _find_line(
        cleaned,
        lambda line: "This ordered item includes text" in line
        and "wraps onto a second line" in line,
    )
    continuation_index = first_index + 1
    bold_index = _find_line(
        cleaned,
        lambda line: "This item contains" in line and "deliberate line break" in line,
    )
    bold_continuation_index = bold_index + 1

    prefix_column = _text_column(cleaned[first_index])
    continuation_indent = _leading_whitespace(cleaned[continuation_index])
    assert continuation_indent >= prefix_column

    bold_prefix_column = _text_column(cleaned[bold_index])
    bold_continuation_indent = _leading_whitespace(cleaned[bold_continuation_index])
    assert bold_continuation_indent >= bold_prefix_column

    if force_plain:
        assert "**bold emphasis**" in cleaned[bold_index]
    else:
        assert has_rich
        assert "bold emphasis" in cleaned[bold_index]
        assert "**" not in cleaned[bold_index]


@pytest.mark.parametrize("force_plain", [False, True])
def test_numbering_restarts_after_intervening_paragraph(
    render_ordered, force_plain: bool
) -> None:
    cleaned, _, _ = render_ordered("ordered_restart.md", force_plain=force_plain)

    first_block_start = _find_line(
        cleaned, lambda line: "First block item one." in line
    )
    first_block_end = _find_line(cleaned, lambda line: "First block item two." in line)
    paragraph_index = _find_line(
        cleaned, lambda line: "Intermediate paragraph between ordered lists." in line
    )
    second_block_start = _find_line(
        cleaned, lambda line: "Second block resets numbering" in line
    )
    second_block_end = _find_line(
        cleaned, lambda line: "Second block continues" in line
    )

    assert first_block_start < first_block_end < paragraph_index < second_block_start
    assert not cleaned[first_block_start - 1].strip()
    assert not cleaned[second_block_end + 1].strip()

    first_digits = [
        re.match(r"\s*(\d+)", line).group(1)
        for line in cleaned[first_block_start : first_block_end + 1]
    ]
    second_digits = [
        re.match(r"\s*(\d+)", line).group(1)
        for line in cleaned[second_block_start : second_block_end + 1]
    ]
    assert first_digits == ["1", "2"]
    assert second_digits == ["1", "2"]


@pytest.mark.parametrize("force_plain", [False, True])
def test_wide_number_prefixes_keep_text_columns_aligned(
    render_ordered, force_plain: bool
) -> None:
    cleaned, _, has_rich = render_ordered(
        "ordered_wide_numbers.md", force_plain=force_plain
    )

    first_index = _find_line(
        cleaned, lambda line: "Single-digit item prepares for widening." in line
    )
    last_single_index = _find_line(
        cleaned, lambda line: "Last single-digit item stays aligned" in line
    )
    double_first_index = _find_line(
        cleaned, lambda line: "First double-digit item" in line
    )
    double_second_index = _find_line(
        cleaned, lambda line: "Second double-digit item" in line
    )

    text_columns = [
        _text_column(cleaned[index])
        for index in (
            first_index,
            last_single_index,
            double_first_index,
            double_second_index,
        )
    ]

    if force_plain:
        assert text_columns[0] == text_columns[1]
        assert text_columns[2] >= text_columns[0]
    else:
        assert has_rich
        assert len(set(text_columns)) == 1
