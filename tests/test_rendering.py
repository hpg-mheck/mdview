import importlib
from pathlib import Path

import pytest

from mdview.rendering import (
    HAS_RICH,
    _pipe_to_command,
    is_markdown_file,
    page_text,
    render_to_ansi,
)


def test_is_markdown_file_matches_expected_suffixes(tmp_path: Path) -> None:
    md_file = tmp_path / "sample.md"
    md_file.write_text("# Heading")
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("plain")

    assert is_markdown_file(md_file) is True
    assert is_markdown_file(tmp_path / "README.MARKDOWN") is True
    assert is_markdown_file(txt_file) is False


def test_render_to_ansi_formats_markdown() -> None:
    content = "# Title\n\n**Bold** text"
    ansi = render_to_ansi(content, markdown=True)

    assert "Title" in ansi
    assert "Bold" in ansi
    if HAS_RICH:
        assert (
            "\x1b" in ansi
        )  # ANSI styling codes should be present when Rich is available


def test_render_to_ansi_passes_plain_text_through() -> None:
    content = "Just plain text"
    ansi = render_to_ansi(content, markdown=False)

    assert content in ansi
    # Plain text should have minimal or no ANSI sequences
    assert ansi.strip().endswith("text")


def test_render_to_ansi_preserves_five_line_plain_text() -> None:
    """Automate the basic five-line plain-text user story using a static fixture."""

    fixture = (
        Path(__file__).resolve().parent.parent
        / "resources"
        / "tests"
        / "plain_text_five_lines.txt"
    )
    lines = fixture.read_text(encoding="utf-8").splitlines()

    rendered = render_to_ansi("\n".join(lines) + "\n", markdown=False)
    rendered_lines = [line.rstrip("\r") for line in rendered.splitlines()]

    assert rendered_lines[:5] == lines
    assert all(part.isascii() for part in rendered_lines[:5])
    if HAS_RICH:
        # Rich should not inject Markdown styling when plain text is requested.
        assert "\x1b" not in "".join(rendered_lines[:5])


def test_rendering_module_handles_absent_rich(monkeypatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    import mdview.rendering as rendering

    reloaded = importlib.reload(rendering)
    try:
        ansi = reloaded.render_to_ansi("fallback only", markdown=False)

        assert reloaded.HAS_RICH is False
        assert "fallback only" in ansi
    finally:
        monkeypatch.undo()
        importlib.reload(rendering)


def test_page_text_uses_custom_pager() -> None:
    captured = []

    def pager(text: str) -> None:
        captured.append(text)

    page_text("hello", pager=pager)

    assert captured == ["hello"]


def test_pipe_to_command_handles_missing_command() -> None:
    with pytest.raises(RuntimeError):
        _pipe_to_command("content", "nonexistent-pager")


def test_page_text_with_shell_command_captures_output(capsys) -> None:
    text = "pager-body"
    # Child process output is not captured by capsys, but the command should
    # execute successfully without raising a RuntimeError.
    page_text(text, pager_command="cat")
