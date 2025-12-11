"""Tests for Markdown bulleted list rendering behavior."""

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
def render_bulleted(monkeypatch):
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
def test_hyphen_list_preserves_spacing_and_alignment(
    render_bulleted, force_plain: bool
) -> None:
    cleaned, _, has_rich = render_bulleted(
        "bulleted_hyphen.md", force_plain=force_plain
    )

    before_index = _find_line(
        cleaned, lambda line: "Introductory paragraph before the hyphen list." in line
    )
    first_index = _find_line(
        cleaned, lambda line: "Hyphen bullet keeps text after marker intact." in line
    )
    last_index = _find_line(
        cleaned, lambda line: "Third hyphen bullet ends before closing prose." in line
    )
    after_index = _find_line(
        cleaned, lambda line: "Closing paragraph after the hyphen list." in line
    )

    assert before_index < first_index < last_index < after_index
    assert not cleaned[first_index - 1].strip()
    assert not cleaned[last_index + 1].strip()

    bullet_lines = cleaned[first_index : last_index + 1]
    markers = [line.lstrip()[:1] for line in bullet_lines]
    offsets = {_leading_whitespace(line) for line in bullet_lines}

    assert len(offsets) == 1
    if force_plain:
        assert markers == ["-"] * len(bullet_lines)
    else:
        assert has_rich
        assert set(markers) == {"•"}


@pytest.mark.parametrize("force_plain", [False, True])
def test_asterisk_list_remains_separate_from_surrounding_text(
    render_bulleted, force_plain: bool
) -> None:
    cleaned, _, has_rich = render_bulleted(
        "bulleted_asterisk.md", force_plain=force_plain
    )

    before_index = _find_line(
        cleaned, lambda line: "Lead-in sentence before the asterisk list." in line
    )
    first_index = _find_line(
        cleaned,
        lambda line: "Asterisk bullet preserves spacing after the marker." in line,
    )
    last_index = _find_line(
        cleaned,
        lambda line: "Third asterisk bullet ends the list before trailing prose."
        in line,
    )
    after_index = _find_line(cleaned, lambda line: "Follow-up paragraph after" in line)

    joined = " ".join(line.strip() for line in cleaned)

    assert before_index < first_index < last_index < after_index
    assert not cleaned[first_index - 1].strip()
    assert not cleaned[last_index + 1].strip()
    assert "Follow-up paragraph after the asterisk list." in joined

    bullet_lines = cleaned[first_index : last_index + 1]
    markers = [line.lstrip()[:1] for line in bullet_lines]

    if force_plain:
        assert markers == ["*"] * len(bullet_lines)
    else:
        assert has_rich
        assert set(markers) == {"•"}


@pytest.mark.parametrize("force_plain", [False, True])
def test_marker_changes_start_new_list_blocks(
    render_bulleted, force_plain: bool
) -> None:
    cleaned, _, has_rich = render_bulleted(
        "bulleted_mixed_markers.md", force_plain=force_plain
    )

    first_hyphen_index = _find_line(
        cleaned, lambda line: "Hyphen bullet one remains aligned." in line
    )
    last_hyphen_index = _find_line(
        cleaned, lambda line: "Hyphen bullet two finishes the first block." in line
    )
    first_asterisk_index = _find_line(
        cleaned,
        lambda line: "Asterisk bullet three begins a new list without a blank line."
        in line,
    )
    after_index = _find_line(
        cleaned, lambda line: "Closing text after mixed markers." in line
    )

    assert first_hyphen_index < last_hyphen_index < first_asterisk_index < after_index
    separators = cleaned[last_hyphen_index + 1 : first_asterisk_index]
    assert any(not line.strip() for line in separators)

    hyphen_markers = cleaned[first_hyphen_index].lstrip()[:1]
    asterisk_markers = cleaned[first_asterisk_index].lstrip()[:1]

    if force_plain:
        assert hyphen_markers == "-"
        assert asterisk_markers == "*"
    else:
        assert has_rich
        assert hyphen_markers == "•"
        assert asterisk_markers == "•"


@pytest.mark.parametrize("force_plain", [False, True])
def test_spacing_and_emphasis_remain_within_bullets(
    render_bulleted, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich = render_bulleted(
        "bulleted_spacing.md", force_plain=force_plain
    )

    first_index = _find_line(
        cleaned, lambda line: "First bullet with" in line and "italic" in line
    )
    second_index = _find_line(
        cleaned, lambda line: "Second bullet follows a deliberate blank line" in line
    )
    third_index = _find_line(
        cleaned,
        lambda line: "Third bullet after double blank lines stays isolated." in line,
    )
    after_index = _find_line(
        cleaned, lambda line: "Trailing text after the spaced" in line
    )

    joined = " ".join(line.strip() for line in cleaned)

    assert first_index < second_index < third_index < after_index
    assert not cleaned[first_index - 1].strip()
    assert not cleaned[after_index - 1].strip()

    between_first_and_second = cleaned[first_index + 1 : second_index]
    between_second_and_third = cleaned[second_index + 1 : third_index]
    blank_threshold = 2 if force_plain or not has_rich else 1

    assert any(not line.strip() for line in between_first_and_second)
    assert (
        sum(1 for line in between_second_and_third if not line.strip())
        >= blank_threshold
    )

    first_line = cleaned[first_index]
    assert "Trailing text after the spaced list." in joined
    if force_plain:
        assert "*italic*" in first_line
    else:
        assert has_rich
        assert "italic" in first_line
        assert "*" not in first_line
        assert any("\x1b" in line for line in raw_lines[first_index : first_index + 1])
