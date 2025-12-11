import importlib
import importlib.util
import re
from pathlib import Path
from typing import List, Tuple

import pytest

import mdview.rendering as rendering

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "resources" / "tests" / "markdown"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def _collapse_spaces(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def render_fenced_code(monkeypatch):
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
def test_fenced_block_preserves_boundaries(
    render_fenced_code, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich, _ = render_fenced_code(
        "fenced_code_basic.md", force_plain=force_plain
    )

    positions = {}
    for index, line in enumerate(cleaned):
        for key, needle in {
            "before": "context.",
            "first": "hello from fence",
            "second": "second line inside",
            "after": "Follow-up paragraph",
        }.items():
            if needle in line:
                positions.setdefault(key, index)

    assert {"before", "first", "second", "after"}.issubset(set(positions))
    assert positions["before"] < positions["first"] <= positions["second"]
    assert positions["second"] < positions["after"]

    if has_rich and not force_plain:
        assert not any("```" in line for line in cleaned)

    if force_plain:
        assert any("```" in line for line in cleaned)
        assert "hello from fence" in "\n".join(cleaned)


@pytest.mark.parametrize("force_plain", [False, True])
def test_language_hints_respect_renderer_capabilities(
    render_fenced_code, force_plain: bool
) -> None:
    cleaned, raw_lines, has_rich, _ = render_fenced_code(
        "fenced_code_language_hints.md", force_plain=force_plain
    )
    joined = _collapse_spaces(" ".join(cleaned))

    assert "def greet(name):" in joined
    assert 'echo "shell run"' in joined
    assert "++>--." in joined

    if has_rich and not force_plain:
        assert any("\x1b" in line for line in raw_lines)
        assert not any("```" in line or "~~~" in line for line in cleaned)

    if force_plain:
        assert any("```python" in line for line in cleaned)
        assert any("~~~bash" in line for line in cleaned)
        assert not any("\x1b" in line for line in raw_lines)


def test_whitespace_inside_fences_stays_intact(render_fenced_code) -> None:
    fixture_path = FIXTURE_DIR / "fenced_code_whitespace.md"
    expected_lines = fixture_path.read_text(encoding="utf-8").splitlines()

    cleaned, _, _, _ = render_fenced_code("fenced_code_whitespace.md", force_plain=True)

    assert cleaned == expected_lines
    assert "\tindented()" in cleaned
    assert any(line.endswith("   ") for line in cleaned)


def test_fallback_mode_surfaces_warning(render_fenced_code) -> None:
    cleaned, raw_lines, has_rich, notices = render_fenced_code(
        "fenced_code_fallback.md", force_plain=True
    )
    joined = " ".join(cleaned)

    assert not has_rich
    assert any("Rich not available" in notice for notice in notices)
    assert "```" in joined
    assert "plain fallback sample()" in joined
    assert not any("\x1b" in line for line in raw_lines)
