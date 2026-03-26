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
    / "images"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
OSC_ESCAPE = re.compile(r"\x1b\][^\x07]*\x07|\x1b\][^\x1b]*\x1b\\")


def _strip_control(text: str) -> str:
    return ANSI_ESCAPE.sub("", OSC_ESCAPE.sub("", text))


@pytest.fixture
def render_images(monkeypatch):
    def _render(filename: str, *, force_plain: bool = False) -> Tuple[List[str], bool]:
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
            cleaned = [_strip_control(line) for line in rendered.splitlines()]
            return cleaned, module.HAS_RICH
        finally:
            if force_plain:
                monkeypatch.undo()
                importlib.reload(rendering)

    return _render


@pytest.mark.parametrize("force_plain", [False, True])
def test_inline_image_basic_keeps_alt_text_visible(render_images, force_plain: bool):
    cleaned, has_rich = render_images("inline_image_basic.md", force_plain=force_plain)
    joined = " ".join(cleaned)

    assert "Alt text" in joined
    if not has_rich or force_plain:
        assert "Alt text (https://example.test/image.png)" in joined


@pytest.mark.parametrize("force_plain", [False, True])
def test_image_adjacent_content_does_not_reorder(render_images, force_plain: bool):
    cleaned, has_rich = render_images(
        "inline_image_adjacent_content.md", force_plain=force_plain
    )
    joined = " ".join(cleaned)

    assert "prefix" in joined
    assert "Build badge" in joined
    assert "reference" in joined
    assert "suffix." in joined
    if not has_rich or force_plain:
        assert "Build badge (https://example.test/badge.svg)" in joined


def test_empty_alt_uses_image_placeholder_in_fallback(render_images):
    cleaned, _ = render_images("inline_image_empty_alt.md", force_plain=True)
    joined = " ".join(cleaned)

    assert "[image] (https://example.test/empty.png)" in joined


def test_missing_url_uses_placeholder_in_fallback(render_images):
    cleaned, _ = render_images("inline_image_missing_url.md", force_plain=True)
    joined = " ".join(cleaned)

    assert "Broken image (missing image URL)" in joined


def test_image_title_is_metadata_only_in_fallback(render_images):
    cleaned, _ = render_images("inline_image_with_title.md", force_plain=True)
    joined = " ".join(cleaned)

    assert "Titled asset (https://example.test/title.png)" in joined
    assert "Preview Title" not in joined
