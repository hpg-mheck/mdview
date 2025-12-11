"""Tests for Markdown inline link rendering and metadata handling."""

import importlib
import importlib.util
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
    / "links"
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
OSC_HYPERLINK = re.compile(r"\x1b]8;[^\\]*\x1b\\")


def _strip_controls(text: str) -> str:
    text = ANSI_ESCAPE.sub("", text)
    return OSC_HYPERLINK.sub("", text)


@pytest.fixture
def render_links(monkeypatch):
    def _render(
        filename: str, *, force_plain: bool = False
    ) -> Tuple[List[str], List[str], str]:
        path = FIXTURE_DIR / filename
        content = path.read_text(encoding="utf-8")
        module = rendering
        original_find_spec = importlib.util.find_spec

        if force_plain:
            monkeypatch.setattr(
                importlib.util,
                "find_spec",
                lambda name: None if name == "rich" else original_find_spec(name),
            )
            module = importlib.reload(rendering)

        try:
            rendered = module.render_to_ansi(content, markdown=True)
            raw_lines = rendered.splitlines()
            cleaned = [_strip_controls(line) for line in raw_lines]
        finally:
            if force_plain:
                monkeypatch.undo()
                importlib.reload(rendering)

        return cleaned, raw_lines, rendered

    return _render


@pytest.mark.skipif(
    not rendering.HAS_RICH, reason="Rich required for hyperlink metadata"
)
def test_inline_link_exposes_url_and_metadata(render_links) -> None:
    cleaned, raw_lines, _ = render_links("inline_link_basic.md")

    assert any("documentation portal" in line for line in cleaned)

    combined_output = "".join(raw_lines)
    assert "https://example.test/docs" in combined_output
    assert "\x1b]8;" in combined_output
    assert combined_output.count("\x1b]8;;") == 1


@pytest.mark.skipif(
    not rendering.HAS_RICH, reason="Rich required for hyperlink metadata"
)
def test_adjacent_links_remain_separate(render_links) -> None:
    cleaned, raw_lines, _ = render_links("inline_link_adjacent_text.md")

    assert any(
        "punctuation:alpha,beta! Keep spacing intact." in line for line in cleaned
    )

    combined_output = "".join(raw_lines)
    assert "https://example.test/alpha" in combined_output
    assert "https://example.test/beta" in combined_output
    assert combined_output.count("\x1b]8;") >= 2


@pytest.mark.skipif(
    not rendering.HAS_RICH, reason="Rich required for hyperlink metadata"
)
def test_emphasis_stays_within_link_text(render_links) -> None:
    cleaned, raw_lines, _ = render_links("inline_link_emphasis.md")

    assert any("Bold and italic link anchors styling" in line for line in cleaned)

    combined_output = "".join(raw_lines)
    open_index = combined_output.find("https://example.test/emphasis")
    assert open_index != -1

    close_index = combined_output.find("\x1b]8;;\x1b\\", open_index)
    assert close_index != -1

    post_link = combined_output[close_index:]
    assert "anchors styling while surrounding text stays plain." in post_link


def test_fallback_renders_visible_urls(render_links) -> None:
    cleaned, raw_lines, _ = render_links(
        "inline_fallback_visibility.md", force_plain=True
    )

    assert any("visible link (https://example.test/plain)" in line for line in cleaned)
    assert any("backup (https://example.test/backup)" in line for line in cleaned)
    assert all("\x1b]8;" not in line for line in raw_lines)


@pytest.mark.skipif(
    not rendering.HAS_RICH, reason="Rich required for hyperlink metadata"
)
def test_multiple_links_expose_distinct_targets(render_links) -> None:
    cleaned, raw_lines, _ = render_links("inline_multiple_links.md")

    assert any("alpha" in line and "beta" in line for line in cleaned)
    assert any("gamma" in line for line in cleaned)

    combined_output = "".join(raw_lines)
    for url in (
        "https://example.test/a",
        "https://example.test/b",
        "https://example.test/gamma",
    ):
        assert url in combined_output
    assert combined_output.count("\x1b]8;") >= 3
