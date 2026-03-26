import importlib
import re
from pathlib import Path
from typing import List

import pytest

import mdview.rendering as rendering

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "tests"
    / "markdown"
    / "escaping"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def _render(filename: str, monkeypatch, force_plain: bool = False) -> List[str]:
    content = (FIXTURE_DIR / filename).read_text(encoding="utf-8")
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
        return [_strip_ansi(line) for line in rendered.splitlines()]
    finally:
        if force_plain:
            monkeypatch.undo()
            importlib.reload(rendering)


@pytest.mark.parametrize("force_plain", [False, True])
def test_escaping_basic_markers_render_literally(monkeypatch, force_plain: bool):
    cleaned = _render("escaping_basic.md", monkeypatch, force_plain=force_plain)
    joined = " ".join(cleaned)

    if force_plain:
        assert "\\*literal\\*" in joined
        assert "\\_literal\\_" in joined
    else:
        assert "*literal*" in joined
        assert "_literal_" in joined
    assert "link" in joined
    assert "img" in joined


@pytest.mark.parametrize("force_plain", [False, True])
def test_escaping_structural_markers_do_not_trigger_structures(
    monkeypatch,
    force_plain: bool,
):
    cleaned = _render("escaping_structural.md", monkeypatch, force_plain=force_plain)
    joined = " ".join(cleaned)

    assert "# Not a heading" in joined
    assert "- Not a bullet" in joined
    assert "*** Not a horizontal rule" in joined
    assert "MDVIEWHEADINGBREAK" not in joined


@pytest.mark.parametrize("force_plain", [False, True])
def test_backslash_escape_sequences_remain_visible(monkeypatch, force_plain: bool):
    cleaned = _render("escaping_backslash.md", monkeypatch, force_plain=force_plain)
    joined = " ".join(cleaned)

    assert "\\*literal star" in joined
    assert "end of line \\" in joined
