"""Tests for Markdown nested list rendering behavior."""

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


@pytest.fixture
def render_nested(monkeypatch):
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
def test_nested_bullets_preserve_depth_and_separation(
    render_nested, force_plain: bool
) -> None:
    cleaned, _, has_rich = render_nested("nested_bulleted.md", force_plain=force_plain)

    before_index = _find_line(
        cleaned,
        lambda line: "Intro paragraph before the nested bulleted list." in line,
    )
    parent_index = _find_line(
        cleaned,
        lambda line: "Parent bullet stays at depth one and introduces children."
        in line,
    )
    child_index = _find_line(
        cleaned,
        lambda line: "Child bullet aligns under the parent indentation." in line,
    )
    grandchild_index = _find_line(
        cleaned,
        lambda line: "Grandchild bullet keeps a deeper offset without merging." in line,
    )
    sibling_index = _find_line(
        cleaned,
        lambda line: "Second child returns to the child depth after the grandchild."
        in line,
    )
    second_parent_index = _find_line(
        cleaned,
        lambda line: "Second parent bullet stays separate from the first set of children."
        in line,
    )
    second_child_index = _find_line(
        cleaned,
        lambda line: "Nested child under the second parent keeps its indentation."
        in line,
    )
    after_index = _find_line(
        cleaned,
        lambda line: "Closing paragraph after the nested bulleted list." in line,
    )

    assert before_index < parent_index < child_index < grandchild_index
    assert grandchild_index < sibling_index < second_parent_index < second_child_index
    assert second_child_index < after_index
    assert not cleaned[parent_index - 1].strip()
    assert not cleaned[after_index - 1].strip()

    parent_indent = _leading_whitespace(cleaned[parent_index])
    child_indent = _leading_whitespace(cleaned[child_index])
    grandchild_indent = _leading_whitespace(cleaned[grandchild_index])
    sibling_indent = _leading_whitespace(cleaned[sibling_index])
    second_parent_indent = _leading_whitespace(cleaned[second_parent_index])
    second_child_indent = _leading_whitespace(cleaned[second_child_index])

    assert parent_indent < child_indent < grandchild_indent
    assert sibling_indent == child_indent
    assert second_parent_indent == parent_indent
    assert second_child_indent > second_parent_indent

    markers = {
        cleaned[parent_index].lstrip()[:1],
        cleaned[child_index].lstrip()[:1],
        cleaned[grandchild_index].lstrip()[:1],
        cleaned[second_parent_index].lstrip()[:1],
        cleaned[second_child_index].lstrip()[:1],
    }
    if force_plain:
        assert markers == {"-"}
    else:
        assert has_rich
        assert markers == {"•"}


@pytest.mark.parametrize("force_plain", [False, True])
def test_mixed_markers_preserve_styles_and_depths(
    render_nested, force_plain: bool
) -> None:
    cleaned, _, has_rich = render_nested(
        "nested_mixed_markers.md", force_plain=force_plain
    )

    lead_index = _find_line(
        cleaned, lambda line: "Lead-in paragraph before mixed marker nesting." in line
    )
    bullet_parent_index = _find_line(
        cleaned, lambda line: "Bulleted parent introduces ordered children." in line
    )
    ordered_child_index = _find_line(
        cleaned,
        lambda line: "First ordered child stays indented beneath the bullet marker."
        in line,
    )
    ordered_second_child_index = _find_line(
        cleaned,
        lambda line: "numeric formatting beneath the bullet." in line,
    )
    second_bullet_parent_index = _find_line(
        cleaned, lambda line: "Second bulleted parent remains at the top level." in line
    )
    ordered_parent_index = _find_line(
        cleaned, lambda line: "Ordered parent introduces bulleted children." in line
    )
    bulleted_child_index = _find_line(
        cleaned,
        lambda line: "Bulleted child keeps its marker under ordered parent indentation."
        in line,
    )
    bulleted_sibling_index = _find_line(
        cleaned,
        lambda line: "Second bulleted child" in line
        or "remains aligned with its sibling marker." in line,
    )
    ordered_parent_second_index = _find_line(
        cleaned,
        lambda line: "Second ordered parent follows the bulleted children." in line,
    )
    trailing_index = _find_line(
        cleaned, lambda line: "Paragraph after mixed marker nesting." in line
    )

    assert lead_index < bullet_parent_index < ordered_child_index
    assert (
        ordered_child_index <= ordered_second_child_index < second_bullet_parent_index
    )
    assert second_bullet_parent_index < ordered_parent_index < bulleted_child_index
    assert bulleted_child_index <= bulleted_sibling_index < ordered_parent_second_index
    assert ordered_parent_second_index < trailing_index

    bullet_indent = _leading_whitespace(cleaned[bullet_parent_index])
    ordered_child_indent = _leading_whitespace(cleaned[ordered_child_index])
    ordered_second_child_indent = _leading_whitespace(
        cleaned[ordered_second_child_index]
    )
    ordered_parent_indent = _leading_whitespace(cleaned[ordered_parent_index])
    bulleted_child_indent = _leading_whitespace(cleaned[bulleted_child_index])
    bulleted_sibling_indent = _leading_whitespace(cleaned[bulleted_sibling_index])

    assert ordered_parent_indent == bullet_indent
    if force_plain:
        assert ordered_child_indent > bullet_indent
        assert ordered_second_child_indent == ordered_child_indent
        assert bulleted_child_indent > ordered_parent_indent
        assert bulleted_sibling_indent == bulleted_child_indent
    else:
        assert has_rich
        assert ordered_child_indent >= 0
        assert ordered_second_child_indent >= 0
        assert bulleted_child_indent >= 0
        assert bulleted_sibling_indent >= 0

    bullet_marker = cleaned[bullet_parent_index].lstrip()[:1]
    child_marker = cleaned[bulleted_child_index].lstrip()[:1]
    if force_plain:
        ordered_digits = [
            re.match(r"\s*(\d+)", cleaned[index]).group(1)
            for index in (
                ordered_child_index,
                ordered_second_child_index,
                ordered_parent_index,
                ordered_parent_second_index,
            )
        ]
        assert ordered_digits[:2] == ["1", "2"]
        assert ordered_digits[2:] == ["1", "2"]
        assert bullet_marker == "-"
        assert child_marker == "-"
    else:
        assert has_rich
        parent_block = " ".join(cleaned[bullet_parent_index:second_bullet_parent_index])
        ordered_parent_block = " ".join(
            cleaned[ordered_parent_index : ordered_parent_second_index + 1]
        )
        assert "1." in parent_block and "2." in parent_block
        assert "1" in ordered_parent_block and "2." in ordered_parent_block
        assert bullet_marker == "•"
        assert child_marker in {"•", "-"}

    gap = cleaned[second_bullet_parent_index + 1 : ordered_parent_index]
    assert any(not line.strip() for line in gap)


@pytest.mark.parametrize("force_plain", [False, True])
def test_blank_lines_between_levels_remain_visible(
    render_nested, force_plain: bool
) -> None:
    cleaned, _, has_rich = render_nested("nested_spacing.md", force_plain=force_plain)

    intro_index = _find_line(
        cleaned, lambda line: "Intro paragraph before spaced nesting." in line
    )
    first_parent_index = _find_line(
        cleaned, lambda line: "Parent item above an intentional blank line." in line
    )
    first_child_index = _find_line(
        cleaned,
        lambda line: "Child item follows the blank line without collapsing back"
        in line,
    )
    second_parent_index = _find_line(
        cleaned,
        lambda line: "Second parent item separated by its own blank line." in line,
    )
    second_child_index = _find_line(
        cleaned,
        lambda line: "Child after the second blank line keeps its indentation." in line,
    )
    closing_index = _find_line(
        cleaned, lambda line: "Closing paragraph after spaced nesting." in line
    )

    assert intro_index < first_parent_index < first_child_index
    assert first_child_index < second_parent_index < second_child_index < closing_index
    assert not cleaned[first_parent_index - 1].strip()
    assert not cleaned[closing_index - 1].strip()

    first_gap = cleaned[first_parent_index + 1 : first_child_index]
    second_gap = cleaned[second_parent_index + 1 : second_child_index]
    assert any(not line.strip() for line in first_gap)
    assert any(not line.strip() for line in second_gap)

    first_parent_indent = _leading_whitespace(cleaned[first_parent_index])
    first_child_indent = _leading_whitespace(cleaned[first_child_index])
    second_parent_indent = _leading_whitespace(cleaned[second_parent_index])
    second_child_indent = _leading_whitespace(cleaned[second_child_index])

    if force_plain:
        assert first_child_indent > first_parent_indent
        assert second_child_indent > second_parent_indent
    else:
        assert has_rich
        assert first_child_indent >= first_parent_indent
        assert second_child_indent >= second_parent_indent


@pytest.mark.parametrize("force_plain", [False, True])
def test_wrapped_nested_items_keep_alignment_by_level(
    render_nested, force_plain: bool
) -> None:
    cleaned, _, has_rich = render_nested("nested_wrapping.md", force_plain=force_plain)

    opening_index = _find_line(
        cleaned, lambda line: "Opening paragraph before wrapped nesting." in line
    )
    parent_index = _find_line(
        cleaned,
        lambda line: "Parent item contains text that wraps across" in line,
    )
    parent_continuation_index = _find_line(
        cleaned,
        lambda line: "multiple lines so indentation stays aligned with the parent depth."
        in line,
    )
    child_index = _find_line(
        cleaned, lambda line: "Child item contains wrapped text that" in line
    )
    child_continuation_index = _find_line(
        cleaned,
        lambda line: "continues onto another line while keeping child indentation."
        in line,
    )
    sibling_index = _find_line(
        cleaned,
        lambda line: "Second child stays at the same depth after the wrapped sibling."
        in line,
    )
    final_parent_index = _find_line(
        cleaned,
        lambda line: "Final parent returns to depth one without inheriting child"
        in line,
    )
    closing_index = _find_line(
        cleaned, lambda line: "Closing paragraph after wrapped nesting." in line
    )

    assert opening_index < parent_index < child_index < sibling_index
    assert sibling_index < final_parent_index < closing_index
    assert not cleaned[parent_index - 1].strip()
    assert not cleaned[closing_index - 1].strip()

    parent_indent = _leading_whitespace(cleaned[parent_index])
    child_indent = _leading_whitespace(cleaned[child_index])
    sibling_indent = _leading_whitespace(cleaned[sibling_index])
    final_parent_indent = _leading_whitespace(cleaned[final_parent_index])
    parent_continuation_indent = _leading_whitespace(cleaned[parent_continuation_index])
    child_continuation_indent = _leading_whitespace(cleaned[child_continuation_index])

    if force_plain:
        assert parent_index < parent_continuation_index < child_index
        assert child_index < child_continuation_index < sibling_index
    else:
        assert has_rich
        assert parent_index <= parent_continuation_index <= child_index
        assert child_index <= child_continuation_index <= sibling_index

    if force_plain:
        assert parent_continuation_indent >= parent_indent
        assert child_continuation_indent >= child_indent
        assert child_indent > parent_indent
        assert sibling_indent == child_indent
        assert final_parent_indent == parent_indent
    else:
        assert has_rich
        assert parent_continuation_indent >= 0
        assert child_continuation_indent >= 0
        assert sibling_indent >= child_indent
        assert final_parent_indent <= child_indent

    if force_plain:
        assert cleaned[parent_index].lstrip().startswith("-")
        assert cleaned[child_index].lstrip().startswith("-")
    else:
        assert has_rich
        assert cleaned[parent_index].lstrip().startswith("•")
        assert cleaned[child_index].lstrip().startswith("•")
