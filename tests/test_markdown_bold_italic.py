import importlib
import re
from pathlib import Path
from typing import List, Tuple

import pytest

import mdview.rendering as rendering

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "tests"
    / "markdown"
    / "bold_italic"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def _remove_combined_markers(text: str) -> str:
    return re.sub(r"(\*{3}|_{3})", "", text)


@pytest.fixture
def render_bold_italic(monkeypatch):
    def _render(
        filename: str,
        *,
        force_plain: bool = False,
        mixed_endings: bool = False,
    ) -> Tuple[List[str], List[str], bool]:
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

        return cleaned, raw_lines, module.HAS_RICH

    return _render


@pytest.mark.parametrize(
    "filename, expected_lines, marker",
    [
        (
            "bold_italic_basic.md",
            [
                "Simple combo span stays ordered.",
                "Combined emphasis on multiple words keeps characters untouched.",
            ],
            "***",
        ),
        (
            "bold_italic_underscore.md",
            [
                "Triple underscore combo mirrors asterisks with the same styling.",
                "Adjacent sequences of words stay grouped without shifting.",
            ],
            "___",
        ),
    ],
)
@pytest.mark.parametrize("force_plain", [False, True])
def test_combined_markers_apply_dual_styling(
    render_bold_italic,
    filename: str,
    expected_lines: List[str],
    marker: str,
    force_plain: bool,
) -> None:
    cleaned, raw_lines, has_rich = render_bold_italic(filename, force_plain=force_plain)
    normalized = [_remove_combined_markers(line) for line in cleaned]
    normalized_text = " ".join(normalized)

    for expected in expected_lines:
        assert expected in normalized_text

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)
        assert not any(marker in line for line in cleaned)

    if force_plain:
        assert any(marker in line for line in cleaned)


@pytest.mark.parametrize("force_plain", [False, True])
def test_combined_emphasis_respects_boundaries(
    render_bold_italic, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich = render_bold_italic(
        "bold_italic_boundaries.md", force_plain=force_plain
    )
    normalized = [_remove_combined_markers(line) for line in cleaned]
    collapsed = " ".join(" ".join(normalized).split())

    assert (
        "Edges around combo should keep spacing tidy without swallowing text."
        in collapsed
    )
    assert (
        "Standalone asterisk neighbors combo * remain literal with punctuation."
        in collapsed
    )
    assert (
        "Paired combo items sit beside commas, periods, and trailing stars."
        in collapsed
    )

    joined = " ".join(cleaned)
    assert "stars***." in joined

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)


@pytest.mark.parametrize("force_plain", [False, True])
def test_unterminated_markers_render_literal(
    render_bold_italic, force_plain: bool
) -> None:
    cleaned, _, _ = render_bold_italic(
        "bold_italic_unterminated.md", force_plain=force_plain
    )
    joined = " ".join(cleaned)
    normalized = " ".join(joined.split())

    assert "***open marker without closure stays literal in output." in normalized
    if force_plain:
        assert (
            "Literal \\_\\_\\_open italic bold run never closes and should show markers."
            in normalized
        )
        assert "Mismatched \\*\\*\\*combo__ sequences remain plain text." in normalized
    else:
        assert (
            "Literal ___open italic bold run never closes and should show markers."
            in normalized
        )
        assert "Mismatched ***combo__ sequences remain plain text." in normalized


@pytest.mark.parametrize("force_plain", [False, True])
def test_escaped_markers_remain_literal(render_bold_italic, force_plain: bool) -> None:
    cleaned, raw_lines, has_rich = render_bold_italic(
        "bold_italic_escape.md", force_plain=force_plain
    )
    joined = " ".join(cleaned)
    normalized = " ".join(joined.split())

    if force_plain:
        assert (
            "\\*\\*\\*escaped\\*\\*\\*\\ markers render literally with trailing backslash"
            " shown." in normalized
        )
        assert "\\_\\_\\_escaped underscores\\_\\_\\_ beside companions." in normalized
    else:
        assert (
            "***escaped***\\ markers render literally with trailing backslash shown."
            in normalized
        )
        assert "___escaped underscores___ beside companions." in normalized

    assert "Trailing escape stays visible at end of line \\" in normalized

    if has_rich and not force_plain:
        assert not any("\x1b" in line for line in raw_lines)


@pytest.mark.parametrize("force_plain", [False, True])
def test_mixed_line_endings_match_native_output(
    render_bold_italic, force_plain: bool
) -> None:
    unix_cleaned, _, _ = render_bold_italic(
        "bold_italic_basic.md", force_plain=force_plain
    )
    mixed_cleaned, _, _ = render_bold_italic(
        "bold_italic_basic.md", force_plain=force_plain, mixed_endings=True
    )

    assert unix_cleaned == mixed_cleaned
