import importlib
import re
from pathlib import Path
from typing import List, Tuple

import pytest

import mdview.rendering as rendering

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "resources" / "tests" / "markdown" / "bold"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def _remove_markdown_markers(text: str) -> str:
    return re.sub(r"(\*\*|__|_)", "", text)


@pytest.fixture
def render_bold(monkeypatch):
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
    "filename, expected_lines, expected_marker",
    [
        (
            "bold_asterisks.md",
            [
                "Plain bold span closing cleanly.",
                "Another line with multiple bold words together to ensure spacing.",
            ],
            "**",
        ),
        (
            "bold_underscores.md",
            [
                "Introductory bold span closing with clarity.",
                "Mix several bold phrases in one sentence for coverage.",
            ],
            "__",
        ),
    ],
)
@pytest.mark.parametrize("force_plain", [False, True])
def test_bold_markers_respect_boundaries(
    render_bold,
    filename: str,
    expected_lines: List[str],
    expected_marker: str,
    force_plain: bool,
) -> None:
    cleaned, raw_lines, has_rich = render_bold(filename, force_plain=force_plain)
    normalized = [_remove_markdown_markers(line) for line in cleaned]
    normalized_text = " ".join(normalized)

    for expected in expected_lines:
        assert expected in normalized_text

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)
        assert not any(expected_marker in line for line in cleaned)

    if force_plain:
        assert any(expected_marker in line for line in cleaned)


@pytest.mark.parametrize("force_plain", [False, True])
def test_adjacent_plain_text_remains_intact(render_bold, force_plain: bool) -> None:
    cleaned, _, _ = render_bold("bold_adjacent_text.md", force_plain=force_plain)
    normalized = [_remove_markdown_markers(line) for line in cleaned]

    assert any(
        "prefixboldsuffix stays glued without stray spaces." in line
        for line in normalized
    )
    assert any("startboldend keeps neighbors intact." in line for line in normalized)


@pytest.mark.parametrize("force_plain", [False, True])
def test_nested_italic_stays_contained(render_bold, force_plain: bool) -> None:
    cleaned, raw_lines, has_rich = render_bold(
        "bold_nested_with_italic.md", force_plain=force_plain
    )
    normalized = [_remove_markdown_markers(line) for line in cleaned]

    assert any(
        "Layered italic inside bold remains contained with trailing text." in line
        for line in normalized
    )
    assert any(
        "Follow with bold italic after to confirm containment." in line
        for line in normalized
    )

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)


@pytest.mark.parametrize("force_plain", [False, True])
def test_punctuation_remains_inside_bold(render_bold, force_plain: bool) -> None:
    cleaned, raw_lines, has_rich = render_bold(
        "bold_with_punctuation.md", force_plain=force_plain
    )
    normalized = [_remove_markdown_markers(line) for line in cleaned]

    assert any(
        "Double-check bold, phrases. and interior punctuation" in line
        for line in normalized
    )
    assert any(
        "Sentence with bold text, centered between commas." in line
        for line in normalized
    )

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)


@pytest.mark.parametrize("force_plain", [False, True])
def test_unmatched_markers_render_as_literal(render_bold, force_plain: bool) -> None:
    cleaned, raw_lines, has_rich = render_bold(
        "bold_unclosed_marker.md", force_plain=force_plain
    )

    joined = " ".join(cleaned)

    if force_plain:
        assert "**unclosed bold marker" in joined
        assert "__bold but never closes" in joined
        assert "opener** must render as text." in joined
        assert "Mixed **marker__ pairs stay literal" in joined
    else:
        assert "unclosed bold marker" in joined
        assert "bold but never closes" in joined
        assert "opener must render as text." in joined
        assert (
            "Mixed marker pairs stay literal" in joined
            or "Mixed **marker__ pairs stay literal" in joined
        )


def test_mixed_line_endings_match_native_output(render_bold) -> None:
    unix_cleaned, _, _ = render_bold("bold_asterisks.md")
    mixed_cleaned, _, _ = render_bold("bold_asterisks.md", mixed_endings=True)

    assert unix_cleaned == mixed_cleaned
