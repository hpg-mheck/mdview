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
    / "inline_code"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def _normalized_text(lines: List[str]) -> str:
    return " ".join(lines)


def _collapse_spaces(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def render_inline_code(monkeypatch):
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
def test_inline_code_stays_monospaced(render_inline_code, force_plain: bool) -> None:
    cleaned, raw_lines, has_rich = render_inline_code(
        "inline_code_basic.md", force_plain=force_plain
    )
    joined = _normalized_text(cleaned)

    assert "Inline code sample stays monospace within the sentence" in joined
    assert "render_me" in joined

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)
        assert "`" not in joined

    if force_plain:
        assert "`render_me`" in joined


@pytest.mark.parametrize("force_plain", [False, True])
def test_spacing_and_punctuation_preserved(
    render_inline_code, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich = render_inline_code(
        "inline_code_spacing.md", force_plain=force_plain
    )
    joined = _normalized_text(cleaned)
    compacted = _collapse_spaces(joined)

    assert any("  padded code" in line for line in cleaned)

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)
        assert "padded code, keeping commas tight" in compacted
        assert "`" not in joined

    if force_plain:
        assert "`  padded code `, keeping commas tight" in joined


@pytest.mark.parametrize("force_plain", [False, True])
def test_escaped_backticks_render_literally(
    render_inline_code, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich = render_inline_code(
        "inline_code_escape.md", force_plain=force_plain
    )
    joined = _normalized_text(cleaned)
    compacted = _collapse_spaces(joined)

    assert "line end`" in joined

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)
        assert "Escaped `backtick` stays literal outside" in compacted
        assert "code \\`tick\\` sample" in compacted

    if force_plain:
        assert "\\`backtick\\` stays literal outside" in joined
        assert "``code \\`tick\\` sample``" in joined


@pytest.mark.parametrize("force_plain", [False, True])
def test_inline_code_respects_boundaries(render_inline_code, force_plain: bool) -> None:
    cleaned, raw_lines, has_rich = render_inline_code(
        "inline_code_boundary.md", force_plain=force_plain
    )
    joined = _normalized_text(cleaned)
    compacted = _collapse_spaces(joined)

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)
        assert "Leading code opens a line before italic emphasis" in compacted
        assert (
            "marker sits beside bold content while tail finishes a line." in compacted
        )
        assert "`Leading`" not in joined

    if force_plain:
        assert "`Leading` code opens a line before *italic* emphasis" in joined
        assert "`marker` sits beside __bold__ content" in joined
        assert "`tail` finishes a line" in joined


@pytest.mark.parametrize("force_plain", [False, True])
def test_mixed_line_endings_remain_equivalent(
    render_inline_code, force_plain: bool
) -> None:
    unix_cleaned, _, _ = render_inline_code(
        "inline_code_basic.md", force_plain=force_plain
    )
    windows_cleaned, _, _ = render_inline_code(
        "inline_code_basic.md", force_plain=force_plain, mixed_endings=True
    )

    assert unix_cleaned == windows_cleaned
