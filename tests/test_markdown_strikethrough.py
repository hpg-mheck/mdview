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
    / "strikethrough"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def _remove_strikethrough_markers(text: str) -> str:
    return re.sub(r"~~", "", text)


def _remove_emphasis_markers(text: str) -> str:
    return re.sub(r"(\*\*|\*|__|_)", "", text)


@pytest.fixture
def render_strikethrough(monkeypatch):
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


@pytest.mark.parametrize("force_plain", [False, True])
def test_strikethrough_markers_respect_boundaries(
    render_strikethrough, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich = render_strikethrough(
        "strikethrough_basic.md", force_plain=force_plain
    )
    normalized = [_remove_strikethrough_markers(line) for line in cleaned]
    combined = " ".join(normalized)

    assert "Simple struck word stays inside the sentence." in combined
    assert "Trailing punctuation after strike lands cleanly." in combined

    if has_rich and not force_plain:
        assert any("\x1b[9m" in line for line in raw_lines)
        assert not any("~~" in line for line in cleaned)

    if force_plain:
        literal = " ".join(cleaned)
        assert "~~struck~~" in literal
        assert "~~strike~~" in literal


@pytest.mark.parametrize("force_plain", [False, True])
def test_adjacent_emphasis_remain_isolated(
    render_strikethrough, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich = render_strikethrough(
        "strikethrough_adjacent_emphasis.md", force_plain=force_plain
    )

    normalized = [
        _remove_emphasis_markers(_remove_strikethrough_markers(line))
        for line in cleaned
    ]
    combined = " ".join(normalized)

    assert "Pair strike next to italic and bold neighbors without merging." in combined
    assert "Close with final marker touching bold but keeping boundaries." in combined

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)
        assert not any(
            marker in line for line in cleaned for marker in ["~~", "*", "_"]
        )

    if force_plain:
        assert any("~~strike~~ next to *italic*" in line for line in cleaned)


@pytest.mark.parametrize("force_plain", [False, True])
def test_unterminated_markers_render_as_literal(
    render_strikethrough, force_plain: bool
) -> None:
    cleaned, _, _ = render_strikethrough(
        "strikethrough_unterminated.md", force_plain=force_plain
    )

    joined = " ".join(cleaned)

    assert "open strikethrough never closes" in joined
    assert "dangling text across lines" in joined

    if force_plain:
        assert "~~open strikethrough" in joined
        assert "holds ~~dangling" in joined


@pytest.mark.parametrize("force_plain", [False, True])
def test_escaped_markers_stay_literal(render_strikethrough, force_plain: bool) -> None:
    cleaned, _, _ = render_strikethrough(
        "strikethrough_escape.md", force_plain=force_plain
    )

    joined = " ".join(cleaned)
    collapsed = joined
    while "\\\\" in collapsed:
        collapsed = collapsed.replace("\\\\", "\\")

    assert "~~escaped~~" in joined
    assert "~~escaped~~\\" in joined
    assert "\\~\\~second\\~\\~\\" in collapsed
    assert "\\" in joined


@pytest.mark.parametrize("force_plain", [False, True])
def test_spacing_and_punctuation_preserved(
    render_strikethrough, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich = render_strikethrough(
        "strikethrough_spacing.md", force_plain=force_plain
    )
    normalized = [_remove_strikethrough_markers(line) for line in cleaned]
    joined = " ".join(normalized)
    collapsed = " ".join(joined.split())

    assert (
        "Preserve punctuation near strike, including commas, and closing periods."
        in collapsed
    )
    assert (
        "Keep markerstight against commas while keeping spaces before periods."
        in collapsed
    )

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)


@pytest.mark.parametrize("force_plain", [False, True])
def test_mixed_line_endings_match_native_output(
    render_strikethrough, force_plain: bool
) -> None:
    unix_cleaned, _, _ = render_strikethrough(
        "strikethrough_basic.md", force_plain=force_plain
    )
    mixed_cleaned, _, _ = render_strikethrough(
        "strikethrough_basic.md", force_plain=force_plain, mixed_endings=True
    )

    assert unix_cleaned == mixed_cleaned
