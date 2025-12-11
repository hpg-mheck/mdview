import importlib
import importlib.util
import re
from pathlib import Path
from typing import Callable, List, Sequence, Tuple

import pytest

import mdview.rendering as rendering

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "tests"
    / "markdown"
    / "horizontal_rules"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def _find_line(lines: Sequence[str], predicate: Callable[[str], bool]) -> int:
    for index, line in enumerate(lines):
        if predicate(line):
            return index
    raise AssertionError("expected line not found")


def _is_separator_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    if re.search(r"[A-Za-z0-9]", stripped):
        return False

    compact = re.sub(r"\s", "", stripped)
    return len(compact) >= 3 and set(compact) <= {"-", "*", "─", "_", "—"}


@pytest.fixture
def render_horizontal_rule(monkeypatch):
    def _render(
        filename: str, *, force_plain: bool = False
    ) -> Tuple[List[str], List[str], bool, List[str]]:
        path = FIXTURE_DIR / filename
        content = path.read_text(encoding="utf-8")

        module = rendering
        has_rich_flag = module.HAS_RICH
        notices: List[str] = []
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
            notices = module.get_fallback_notices()
            has_rich_flag = module.HAS_RICH
        finally:
            if force_plain:
                monkeypatch.undo()
                importlib.reload(rendering)

        return cleaned, raw_lines, has_rich_flag, notices

    return _render


@pytest.mark.parametrize("force_plain", [False, True])
def test_basic_horizontal_rules_render_as_separators(
    render_horizontal_rule, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich, notices = render_horizontal_rule(
        "horizontal_rule_basic.md", force_plain=force_plain
    )

    before_index = _find_line(cleaned, lambda line: "before the rules" in line)
    between_index = _find_line(
        cleaned, lambda line: "Paragraph between the rules" in line
    )
    after_index = _find_line(cleaned, lambda line: "Closing paragraph" in line)

    separators = [
        index for index, line in enumerate(cleaned) if _is_separator_line(line)
    ]

    assert before_index < between_index < after_index
    assert any(before_index < index < between_index for index in separators)
    assert any(between_index < index < after_index for index in separators)

    if force_plain:
        assert not has_rich
        assert all(cleaned[index].strip() == "---" for index in separators[:2])
        assert any("horizontal rules" in notice.lower() for notice in notices)
    else:
        assert has_rich
        assert any("\x1b" in line for line in raw_lines)


@pytest.mark.parametrize("force_plain", [False, True])
def test_spacing_variations_are_normalized(
    render_horizontal_rule, force_plain: bool
) -> None:
    cleaned, _, has_rich, _ = render_horizontal_rule(
        "horizontal_rule_spacing.md", force_plain=force_plain
    )
    joined = " ".join(cleaned)

    assert "should remain literal text rather than a separator." in joined
    assert "mixes markers and must not count as a rule." in joined

    literal_lines = [
        line for line in cleaned if "literal text rather than a separator" in line
    ]
    assert literal_lines
    assert all(not _is_separator_line(line) for line in literal_lines)

    separators = [line for line in cleaned if _is_separator_line(line)]
    assert len(separators) >= 4

    if force_plain:
        assert not has_rich
        assert all(line.strip() == "---" for line in separators[:4])
    else:
        assert has_rich


@pytest.mark.parametrize("force_plain", [False, True])
def test_trailing_text_lines_render_literally(
    render_horizontal_rule, force_plain: bool
) -> None:
    cleaned, _, has_rich, notices = render_horizontal_rule(
        "horizontal_rule_text_suppression.md", force_plain=force_plain
    )

    assert any(
        "must render as plain text instead of a rule" in line for line in cleaned
    )
    assert any("*** 12345" in line for line in cleaned)

    separators = [line for line in cleaned if _is_separator_line(line)]
    assert len(separators) >= 2

    trailing_lines = [line for line in cleaned if "trailing words" in line]
    assert trailing_lines and not any(
        _is_separator_line(line) for line in trailing_lines
    )

    if force_plain:
        assert not has_rich
        assert all(line.strip() == "---" for line in separators[:2])
        assert any("horizontal rules" in notice.lower() for notice in notices)
    else:
        assert has_rich
