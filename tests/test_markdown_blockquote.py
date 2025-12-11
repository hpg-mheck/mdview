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
    / "blockquote"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PREFIX_CHARS = (">", "▌")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def _find_line(lines: List[str], predicate: Callable[[str], bool]) -> int:
    for index, line in enumerate(lines):
        if predicate(line):
            return index
    raise AssertionError("expected line not found")


def _has_quote_prefix(line: str) -> bool:
    return line.lstrip().startswith(PREFIX_CHARS)


def _prefix_depth(line: str) -> int:
    depth = 0
    index = 0
    stripped = line.lstrip()

    while index < len(stripped):
        char = stripped[index]
        if char in PREFIX_CHARS:
            depth += 1
            index += 1
            if index < len(stripped) and stripped[index] == " ":
                index += 1
            continue
        break

    return depth


@pytest.fixture
def render_blockquote(monkeypatch):
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
            has_rich_flag = module.HAS_RICH
        finally:
            if force_plain:
                monkeypatch.undo()
                importlib.reload(rendering)

        return cleaned, raw_lines, has_rich_flag

    return _render


@pytest.mark.parametrize("force_plain", [False, True])
def test_basic_blockquote_preserves_prefixes_and_boundaries(
    render_blockquote, force_plain: bool
) -> None:
    cleaned, _, has_rich = render_blockquote(
        "blockquote_basic.md", force_plain=force_plain
    )

    before_index = _find_line(
        cleaned, lambda line: "Introductory paragraph before the quote." in line
    )
    quote_index = _find_line(
        cleaned, lambda line: "Single-level quote line introducing the concept." in line
    )
    after_index = _find_line(
        cleaned, lambda line: "Closing paragraph after the quote" in line
    )

    assert before_index < quote_index < after_index
    assert "Second quoted line" in " ".join(cleaned[quote_index:after_index])
    assert _has_quote_prefix(cleaned[quote_index])

    if force_plain:
        assert cleaned[quote_index].lstrip().startswith(">")
    else:
        assert has_rich
        assert cleaned[quote_index].lstrip().startswith(PREFIX_CHARS)


@pytest.mark.parametrize("force_plain", [False, True])
def test_nested_blockquote_levels_stay_distinct(
    render_blockquote, force_plain: bool
) -> None:
    cleaned, _, _ = render_blockquote("blockquote_nested.md", force_plain=force_plain)

    parent_index = _find_line(
        cleaned, lambda line: "Parent quote level maintains prefix visibility." in line
    )
    child_index = _find_line(
        cleaned, lambda line: "Child quote text stays nested" in line
    )

    parent_depth = _prefix_depth(cleaned[parent_index])
    child_depth = _prefix_depth(cleaned[child_index])

    assert parent_depth >= 1
    assert child_depth > parent_depth

    normalized = " ".join(line.strip() for line in cleaned)
    normalized = (
        normalized.replace("▌ ", "").replace("▌", "").replace("> ", "").replace(">", "")
    )
    assert "Normal text after the quotes returns to baseline." in normalized

    if force_plain:
        assert cleaned[parent_index].lstrip().startswith(">")


@pytest.mark.parametrize("force_plain", [False, True])
def test_blockquote_emphasis_stays_within_prefix(
    render_blockquote, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich = render_blockquote(
        "blockquote_emphasis.md", force_plain=force_plain
    )

    normalized = " ".join(line.strip() for line in cleaned)
    normalized = (
        normalized.replace("▌ ", "").replace("▌", "").replace("> ", "").replace(">", "")
    )
    normalized = normalized.replace("*", "")
    for phrase in (
        "italic emphasis that should stay inside the content",
        "bold markers that must not leak into prefixes",
        "bold and italic emphasis stays scoped within the quote",
    ):
        assert phrase in normalized

    assert all(_has_quote_prefix(line) for line in cleaned if line.strip())

    joined = " ".join(cleaned)
    if force_plain:
        assert "*italic*" in joined
        assert "**bold**" in joined
    else:
        assert has_rich
        assert not any("*italic*" in line or "**bold**" in line for line in cleaned)
        assert any("\x1b" in line for line in raw_lines)


@pytest.mark.parametrize("force_plain", [False, True])
def test_blockquote_spacing_remains_intact(
    render_blockquote, force_plain: bool
) -> None:
    cleaned, _, _ = render_blockquote("blockquote_spacing.md", force_plain=force_plain)

    assert "punctuation !?" in " ".join(cleaned)
    assert any(_has_quote_prefix(line) for line in cleaned if line.strip())

    if force_plain:
        assert any(
            line.startswith(
                ">  Leading spaces remain inside the quoted content without trimming."
            )
            for line in cleaned
        )
    else:
        assert any(
            line.lstrip().startswith(PREFIX_CHARS) for line in cleaned if line.strip()
        )


@pytest.mark.parametrize("force_plain", [False, True])
def test_blockquote_multiline_stays_grouped(
    render_blockquote, force_plain: bool
) -> None:
    cleaned, _, _ = render_blockquote(
        "blockquote_multiline.md", force_plain=force_plain
    )

    before_index = _find_line(
        cleaned, lambda line: "Intro text before the multi-line quote." in line
    )
    quote_index = _find_line(
        cleaned, lambda line: "First quoted line that should stay grouped" in line
    )
    after_index = _find_line(
        cleaned, lambda line: "Follow-up paragraph after the quote block" in line
    )

    assert before_index < quote_index < after_index
    assert _has_quote_prefix(cleaned[quote_index])
    assert any(not line.strip() for line in cleaned[before_index + 1 : quote_index])
    assert any(not line.strip() for line in cleaned[quote_index + 1 : after_index])
