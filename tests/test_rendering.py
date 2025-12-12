import importlib
import sys
from pathlib import Path
from typing import List, Tuple

import pytest

import mdview.rendering as rendering
from mdview.rendering import (
    HAS_RICH,
    _format_pipe_tables,
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


def test_format_pipe_tables_aligns_columns_and_skips_fences() -> None:
    fixture = (
        Path(__file__).resolve().parent.parent
        / "resources"
        / "tests"
        / "markdown_table_alignment.md"
    )
    formatted = _format_pipe_tables(fixture.read_text(encoding="utf-8"))
    lines = formatted.splitlines()

    assert lines[:5] == [
        "| name         | score | delta |",
        "| :----------- | ----: | :---: |",
        "| Ada Lovelace |    99 |   +3  |",
        "| Bob          |     7 |   -2  |",
        "| Carol        |    13 |   0   |",
    ]
    assert lines[-4:] == [
        "```",
        "| not | a | table |",
        "| --- | --- | --- |",
        "```",
    ]


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


def test_render_to_ansi_formats_tables_without_rich(monkeypatch) -> None:
    original_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: None if name == "rich" else original_find_spec(name),
    )

    import mdview.rendering as rendering

    reloaded = importlib.reload(rendering)
    fixture = (
        Path(__file__).resolve().parent.parent
        / "resources"
        / "tests"
        / "markdown_table_alignment.md"
    )
    ansi = reloaded.render_to_ansi(fixture.read_text(encoding="utf-8"), markdown=True)
    try:
        assert "| name         | score | delta |" in ansi
        assert "Outside table paragraph." in ansi
        assert "| not | a | table |" in ansi
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


def test_page_text_records_prompt_toolkit_fallback(monkeypatch) -> None:
    original_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: None if name == "prompt_toolkit" else original_find_spec(name),
    )

    import mdview.rendering as rendering

    reloaded = importlib.reload(rendering)
    captured: List[str] = []

    import pydoc

    monkeypatch.setattr(pydoc, "pager", lambda text: captured.append(text))

    try:
        reloaded.page_text("sample")
        notices = reloaded.get_fallback_notices()
        assert any("prompt_toolkit" in notice for notice in notices)
        assert captured == ["sample"]
    finally:
        monkeypatch.undo()
        importlib.reload(rendering)


def test_prompt_toolkit_pager_rerenders_on_resize(monkeypatch) -> None:
    class DummyRenderInfo:
        def __init__(self, window_width: int, window_height: int) -> None:
            self.window_width = window_width
            self.window_height = window_height

    class DummySize:
        def __init__(self, columns: int, rows: int) -> None:
            self.columns = columns
            self.rows = rows

    class DummyOutput:
        def __init__(self) -> None:
            self.size = DummySize(40, 10)

        def get_size(self) -> DummySize:
            return self.size

    app_registry: List["DummyApplication"] = []

    controls: List["DummyFormattedTextControl"] = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text
            self.rendered: List[List[Tuple[str, str]]] = []
            controls.append(self)

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(40, 10)
            self.vertical_scroll = 0

    class DummyKeyBindings:
        def add(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class DummyLayout:
        def __init__(self, container) -> None:
            self.container = container

    class DummyStyle:
        @classmethod
        def from_dict(cls, mapping):
            return mapping

    class DummyApplication:
        def __init__(self, layout, key_bindings, full_screen, style) -> None:
            self.layout = layout
            self.invalidate_called = 0
            self.output = DummyOutput()
            app_registry.append(self)

        def invalidate(self) -> None:
            self.invalidate_called += 1

        def run(self) -> None:
            window = self.layout.container
            window.content.rendered.append(window.content.text_func())
            self.output.size = DummySize(60, 10)
            window.content.rendered.append(window.content.text_func())
            window.render_info = DummyRenderInfo(60, 10)

    def get_dummy_app() -> DummyApplication:
        return app_registry[-1]

    def fake_components():
        return (
            DummyApplication,
            DummyKeyBindings,
            DummyLayout,
            DummyWindow,
            DummyFormattedTextControl,
            DummyStyle,
            get_dummy_app,
        )

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(rendering, "_prompt_toolkit_components", fake_components)

    resized_widths: List[int] = []

    def render_on_resize(width: int) -> str:
        resized_widths.append(width)
        return "resized content"

    assert rendering._attempt_prompt_toolkit_pager(
        "initial", render_on_resize=render_on_resize
    )

    # The dummy control stores render output during application.run().
    # Capture the instance to assert against rendered content.
    assert resized_widths == [60]
    assert len(controls) == 1
    assert controls[0].rendered[0][0][1].strip() == "initial"
    assert controls[0].rendered[1][0][1].strip() == "resized content"


def test_prompt_toolkit_pager_pads_lines_after_shrinking(monkeypatch) -> None:
    class DummyRenderInfo:
        def __init__(self, window_width: int, window_height: int) -> None:
            self.window_width = window_width
            self.window_height = window_height

    class DummySize:
        def __init__(self, columns: int, rows: int) -> None:
            self.columns = columns
            self.rows = rows

    class DummyOutput:
        def __init__(self) -> None:
            self.size = DummySize(50, 10)

        def get_size(self) -> DummySize:
            return self.size

    app_registry: List["DummyApplication"] = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text
            self.rendered: List[List[Tuple[str, str]]] = []

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(50, 10)
            self.vertical_scroll = 0

    class DummyKeyBindings:
        def add(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class DummyLayout:
        def __init__(self, container) -> None:
            self.container = container

    class DummyStyle:
        @classmethod
        def from_dict(cls, mapping):
            return mapping

    class DummyApplication:
        def __init__(self, layout, key_bindings, full_screen, style) -> None:
            self.layout = layout
            self.invalidate_called = 0
            self.output = DummyOutput()
            app_registry.append(self)

        def invalidate(self) -> None:
            self.invalidate_called += 1

        def run(self) -> None:
            window = self.layout.container
            window.content.rendered.append(window.content.text_func())
            self.output.size = DummySize(20, 10)
            window.render_info = DummyRenderInfo(20, 10)
            window.content.rendered.append(window.content.text_func())

    def get_dummy_app() -> DummyApplication:
        return app_registry[-1]

    def fake_components():
        return (
            DummyApplication,
            DummyKeyBindings,
            DummyLayout,
            DummyWindow,
            DummyFormattedTextControl,
            DummyStyle,
            get_dummy_app,
        )

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(rendering, "_prompt_toolkit_components", fake_components)

    resized_widths: List[int] = []

    def render_on_resize(width: int) -> str:
        resized_widths.append(width)
        return "narrow"

    assert rendering._attempt_prompt_toolkit_pager(
        "wide", render_on_resize=render_on_resize
    )

    assert resized_widths == [20]
    control = app_registry[-1].layout.container.content
    assert len(control.rendered) == 2
    resized_render = "".join(part for _, part in control.rendered[1])
    # Remove the trailing newline added by the renderer before measuring width.
    resized_line = resized_render.rstrip("\n")
    assert len(resized_line) == 20
