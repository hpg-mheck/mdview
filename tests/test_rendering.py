import importlib
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import mdview.rendering as rendering
from mdview.rendering import (
    HAS_RICH,
    _format_pipe_tables,
    is_markdown_file,
    page_text,
    render_to_ansi,
)


def test_render_to_ansi_routes_content_through_intake(monkeypatch) -> None:
    import mdview.rendering as rendering

    captured = {"called": False}

    def _fake_ingest(content: str, markdown: bool):
        from mdview.dom import Block, Document, Line

        captured["called"] = True
        captured["content"] = content
        captured["markdown"] = markdown
        return Document(
            blocks=(Block(block_id="b1", lines=(Line.from_source(content),)),),
            source_markdown=markdown,
            trailing_newline=content.endswith(("\n", "\r\n")),
            original_text=content,
        )

    monkeypatch.setattr(rendering, "ingest_content", _fake_ingest)
    ansi = rendering.render_to_ansi("intake-smoke", markdown=False)

    assert captured["called"] is True
    assert captured["content"] == "intake-smoke"
    assert captured["markdown"] is False
    assert "intake-smoke" in ansi


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


def test_render_to_ansi_keeps_bullet_continuation_lines_together() -> None:
    content = (
        "- Renders Markdown using the\n"
        "  [rich](https://github.com/Textualize/rich) library for readable terminal\n"
        "  formatting.\n"
    )
    rendered = render_to_ansi(content, markdown=True, width=80)
    osc_escape = re.compile(r"\x1b\][^\x1b\x07]*(?:\x1b\\|\x07)")
    ansi_escape = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    cleaned_lines = [
        ansi_escape.sub("", osc_escape.sub("", line)) for line in rendered.splitlines()
    ]

    start = next(
        index
        for index, line in enumerate(cleaned_lines)
        if "Renders Markdown using the" in line
    )
    continuation = next(
        index
        for index, line in enumerate(cleaned_lines)
        if "rich library for readable terminal" in line
    )
    tail = next(
        index for index, line in enumerate(cleaned_lines) if "formatting." in line
    )
    between = cleaned_lines[start + 1 : continuation]
    assert all(line.strip() for line in between)
    assert continuation <= tail
    assert all(line.strip() for line in cleaned_lines[continuation + 1 : tail])


def test_render_to_ansi_keeps_plain_bullet_continuations_together() -> None:
    content = (
        "- Uses an internal viewport with integrated vertical and horizontal\n"
        "  navigation.\n"
        "- Graceful fallback to plain-text output if `rich` is unavailable in the\n"
        "  environment.\n"
    )
    rendered = render_to_ansi(content, markdown=True, width=100)
    osc_escape = re.compile(r"\x1b\][^\x1b\x07]*(?:\x1b\\|\x07)")
    ansi_escape = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    cleaned_lines = [
        ansi_escape.sub("", osc_escape.sub("", line)) for line in rendered.splitlines()
    ]

    first_start = next(
        index
        for index, line in enumerate(cleaned_lines)
        if "integrated vertical and horizontal" in line
    )
    first_tail = next(
        index for index, line in enumerate(cleaned_lines) if "navigation." in line
    )
    second_start = next(
        index
        for index, line in enumerate(cleaned_lines)
        if "is unavailable in the" in line
    )
    second_tail = next(
        index for index, line in enumerate(cleaned_lines) if "environment." in line
    )

    assert first_start <= first_tail
    assert all(line.strip() for line in cleaned_lines[first_start + 1 : first_tail])
    assert second_start <= second_tail
    assert all(line.strip() for line in cleaned_lines[second_start + 1 : second_tail])


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


def test_render_to_ansi_reflows_plain_text_when_enabled() -> None:
    content = (
        "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu\n"
        "second line remains present\n"
    )
    rendered = render_to_ansi(
        content,
        markdown=False,
        reflow_mode="all",
        width=30,
    )
    lines = rendered.splitlines()
    joined = " ".join(lines)

    assert "alpha beta gamma delta epsilon" in lines[0]
    assert any("zeta eta theta iota" in line for line in lines)
    assert "second line remains present" in joined


def test_render_to_ansi_respects_no_reflow_mode_for_plain_text() -> None:
    content = "plain line one\nplain line two\n"
    rendered = render_to_ansi(
        content,
        markdown=False,
        reflow_mode="none",
        width=10,
    )

    assert rendered == content


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


def test_page_text_records_prompt_toolkit_fallback(monkeypatch, capsys) -> None:
    original_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: None if name == "prompt_toolkit" else original_find_spec(name),
    )

    import mdview.rendering as rendering

    reloaded = importlib.reload(rendering)

    try:
        reloaded.page_text("sample")
        captured = capsys.readouterr()
        notices = reloaded.get_fallback_notices()
        assert any("prompt_toolkit" in notice for notice in notices)
        assert captured.out == "sample\n"
    finally:
        monkeypatch.undo()
        importlib.reload(rendering)


def test_render_to_ansi_does_not_write_directly_to_stdout(capsys) -> None:
    render_to_ansi("# Heading\n\nBody\n", markdown=True)
    captured = capsys.readouterr()
    assert captured.out == ""


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
    def _rendered_text(segments: List[Tuple[str, str]]) -> str:
        return "".join(text for _, text in segments).strip()

    assert resized_widths == [60]
    assert len(controls) == 1
    assert _rendered_text(controls[0].rendered[0]) == "initial"
    assert _rendered_text(controls[0].rendered[1]) == "resized content"


def test_prompt_toolkit_control_kwargs_are_version_compatible(monkeypatch) -> None:
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
            self.size = DummySize(40, 8)

        def get_size(self) -> DummySize:
            return self.size

    app_registry: List["DummyApplication"] = []

    class StrictFormattedTextControl:
        # Mirrors prompt_toolkit 3.0.x signature subset and rejects unknown args.
        def __init__(
            self,
            text="",
            style: str = "",
            focusable: bool = False,
            key_bindings=None,
            show_cursor: bool = True,
            modal: bool = False,
            get_cursor_position=None,
        ) -> None:
            self.text_func = text

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(40, 8)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

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
            self.output = DummyOutput()
            app_registry.append(self)

        def run(self) -> None:
            self.layout.container.content.text_func()

    def get_dummy_app() -> DummyApplication:
        return app_registry[-1]

    def fake_components():
        return (
            DummyApplication,
            DummyKeyBindings,
            DummyLayout,
            DummyWindow,
            StrictFormattedTextControl,
            DummyStyle,
            get_dummy_app,
        )

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(rendering, "_prompt_toolkit_components", fake_components)

    assert rendering._attempt_prompt_toolkit_pager("compatibility check")


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


def test_prompt_toolkit_pager_strips_escape_sequence_fragments(monkeypatch) -> None:
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
            self.size = DummySize(60, 12)

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
            self.render_info: DummyRenderInfo = DummyRenderInfo(60, 12)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

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
            self.output = DummyOutput()
            app_registry.append(self)

        def run(self) -> None:
            window = self.layout.container
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
    text = (
        "prefix "
        "\x1b[1mBold\x1b[0m "
        "\x1b]8;id=1;https://example.test\x1b\\"
        "Link"
        "\x1b]8;;\x1b\\"
    )

    assert rendering._attempt_prompt_toolkit_pager(text)

    control = app_registry[-1].layout.container.content
    rendered = "".join(part for _, part in control.rendered[0])
    assert "Bold" in rendered
    assert "Link" in rendered
    assert "\x1b" not in rendered
    assert "]8;" not in rendered


def test_prompt_toolkit_pager_recenters_on_resize(monkeypatch) -> None:
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
            self.size = DummySize(50, 6)

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
            self.render_info: DummyRenderInfo = DummyRenderInfo(50, 6)
            self.vertical_scroll = 4

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
            self.window: DummyWindow
            app_registry.append(self)

        def invalidate(self) -> None:
            self.invalidate_called += 1

        def run(self) -> None:
            window = self.layout.container
            self.window = window
            window.content.rendered.append(window.content.text_func())
            self.output.size = DummySize(50, 10)
            window.render_info = DummyRenderInfo(50, 10)
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

    content = "\n".join(f"line {index}" for index in range(20))

    def render_on_resize(width: int) -> str:
        resized_widths.append(width)
        return content

    assert rendering._attempt_prompt_toolkit_pager(
        content, render_on_resize=render_on_resize
    )

    assert resized_widths == [50]
    application = app_registry[-1]
    assert application.window.vertical_scroll == 2


def test_prompt_toolkit_pager_supports_horizontal_panning(monkeypatch) -> None:
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
            self.size = DummySize(10, 6)

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
            self.render_info: DummyRenderInfo = DummyRenderInfo(10, 6)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

    class DummyKeyBindings:
        def __init__(self) -> None:
            self.handlers = {}

        def add(self, *keys, **kwargs):
            def decorator(func):
                for key in keys:
                    self.handlers[key] = func
                return func

            return decorator

    class DummyLayout:
        def __init__(self, container) -> None:
            self.container = container

    class DummyStyle:
        @classmethod
        def from_dict(cls, mapping):
            return mapping

    class DummyEvent:
        def __init__(self, app) -> None:
            self.app = app

    class DummyApplication:
        def __init__(self, layout, key_bindings, full_screen, style) -> None:
            self.layout = layout
            self.key_bindings = key_bindings
            self.invalidate_called = 0
            self.output = DummyOutput()
            self.window: DummyWindow
            app_registry.append(self)

        def invalidate(self) -> None:
            self.invalidate_called += 1

        def run(self) -> None:
            self.window = self.layout.container
            self.window.content.rendered.append(self.window.content.text_func())
            event = DummyEvent(self)
            self.key_bindings.handlers["right"](event)
            self.key_bindings.handlers["right"](event)
            self.key_bindings.handlers["left"](event)

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

    assert rendering._attempt_prompt_toolkit_pager("0123456789abcdefghij")
    assert app_registry[-1].window.horizontal_scroll == 1


def test_prompt_toolkit_pager_switches_documents_with_n_and_p(monkeypatch) -> None:
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

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text
            self.rendered: List[List[Tuple[str, str]]] = []

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(40, 10)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

    class DummyKeyBindings:
        def __init__(self) -> None:
            self.handlers = {}

        def add(self, *keys, **kwargs):
            def decorator(func):
                for key in keys:
                    self.handlers[key] = func
                return func

            return decorator

    class DummyLayout:
        def __init__(self, container) -> None:
            self.container = container

    class DummyStyle:
        @classmethod
        def from_dict(cls, mapping):
            return mapping

    class DummyEvent:
        def __init__(self, app) -> None:
            self.app = app

    class DummyApplication:
        def __init__(self, layout, key_bindings, full_screen, style) -> None:
            self.layout = layout
            self.key_bindings = key_bindings
            self.output = DummyOutput()
            app_registry.append(self)

        def invalidate(self) -> None:
            return

        def run(self) -> None:
            window = self.layout.container
            event = DummyEvent(self)
            window.content.rendered.append(window.content.text_func())
            self.key_bindings.handlers["n"](event)
            window.content.rendered.append(window.content.text_func())
            self.key_bindings.handlers["p"](event)
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

    active = {"index": 0}
    documents = ["doc-zero", "doc-one"]
    calls: List[int] = []

    def switch_document(delta: int, width: int) -> Optional[str]:
        target = active["index"] + delta
        if target < 0 or target >= len(documents):
            return None
        active["index"] = target
        calls.append(delta)
        return documents[target]

    assert rendering._attempt_prompt_toolkit_pager(
        documents[0],
        switch_document=switch_document,
    )

    control = app_registry[-1].layout.container.content
    assert [
        "".join(text for _, text in segments).strip() for segments in control.rendered
    ] == [
        "doc-zero",
        "doc-one",
        "doc-zero",
    ]
    assert calls == [1, -1]


def test_prompt_toolkit_pager_emits_mil_ui_events(monkeypatch) -> None:
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
            self.size = DummySize(20, 6)

        def get_size(self) -> DummySize:
            return self.size

    app_registry: List["DummyApplication"] = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(20, 2)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

    class DummyKeyBindings:
        def __init__(self) -> None:
            self.handlers = {}

        def add(self, *keys, **kwargs):
            def decorator(func):
                for key in keys:
                    self.handlers[key] = func
                return func

            return decorator

    class DummyLayout:
        def __init__(self, container) -> None:
            self.container = container

    class DummyStyle:
        @classmethod
        def from_dict(cls, mapping):
            return mapping

    class DummyEvent:
        def __init__(self, app) -> None:
            self.app = app

    class DummyApplication:
        def __init__(self, layout, key_bindings, full_screen, style) -> None:
            self.layout = layout
            self.key_bindings = key_bindings
            self.output = DummyOutput()
            app_registry.append(self)

        def invalidate(self) -> None:
            return

        def exit(self) -> None:
            return

        def run(self) -> None:
            event = DummyEvent(self)
            self.layout.container.content.text_func()
            self.key_bindings.handlers["j"](event)
            self.key_bindings.handlers["l"](event)
            self.key_bindings.handlers["q"](event)

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

    events = []

    def logger(action: str, context: dict) -> None:
        events.append((action, context))

    assert rendering._attempt_prompt_toolkit_pager(
        "line-one\nline-two",
        ui_event_logger=logger,
        document_count=2,
        current_document_index=lambda: 1,
    )

    actions = [action for action, _ in events]
    assert "scroll-down" in actions
    assert "pan-right" in actions
    assert "quit" in actions
    assert all(context["document_index"] == 2 for _, context in events)


def test_prompt_toolkit_pager_accepts_modified_navigation_keys(
    monkeypatch,
) -> None:
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
            self.size = DummySize(20, 6)

        def get_size(self) -> DummySize:
            return self.size

    app_registry: List["DummyApplication"] = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(20, 2)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

    class DummyKeyBindings:
        def __init__(self) -> None:
            self.handlers = {}

        def add(self, *keys, **kwargs):
            def decorator(func):
                for key in keys:
                    self.handlers[key] = func
                return func

            return decorator

    class DummyLayout:
        def __init__(self, container) -> None:
            self.container = container

    class DummyStyle:
        @classmethod
        def from_dict(cls, mapping):
            return mapping

    class DummyEvent:
        def __init__(self, app) -> None:
            self.app = app

    class DummyApplication:
        def __init__(self, layout, key_bindings, full_screen, style) -> None:
            self.layout = layout
            self.key_bindings = key_bindings
            self.output = DummyOutput()
            app_registry.append(self)

        def invalidate(self) -> None:
            return

        def exit(self) -> None:
            return

        def run(self) -> None:
            event = DummyEvent(self)
            self.layout.container.content.text_func()
            self.key_bindings.handlers["s-down"](event)
            self.key_bindings.handlers["c-up"](event)
            self.key_bindings.handlers["c-s-down"](event)
            self.key_bindings.handlers["c-pagedown"](event)
            self.key_bindings.handlers["s-pageup"](event)
            self.key_bindings.handlers["q"](event)

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

    assert rendering._attempt_prompt_toolkit_pager(
        "line-0\nline-1\nline-2\nline-3\nline-4\nline-5",
        viewport_rows=2,
    )
    assert app_registry[-1].layout.container.vertical_scroll == 1
    assert "escape" not in app_registry[-1].key_bindings.handlers


def test_prompt_toolkit_pager_honors_automation_timeout(monkeypatch) -> None:
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
            self.size = DummySize(20, 6)

        def get_size(self) -> DummySize:
            return self.size

    class DummyTimer:
        def __init__(self, interval, callback) -> None:
            self.interval = interval
            self.callback = callback
            self.cancelled = False
            self.started = False

        def start(self) -> None:
            self.started = True
            self.callback()

        def cancel(self) -> None:
            self.cancelled = True

    app_registry: List["DummyApplication"] = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(20, 2)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

    class DummyKeyBindings:
        def __init__(self) -> None:
            self.handlers = {}

        def add(self, *keys, **kwargs):
            def decorator(func):
                for key in keys:
                    self.handlers[key] = func
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
            self.key_bindings = key_bindings
            self.output = DummyOutput()
            self.exit_called = False
            app_registry.append(self)

        def invalidate(self) -> None:
            return

        def exit(self) -> None:
            self.exit_called = True

        def run(self) -> None:
            self.layout.container.content.text_func()

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
    monkeypatch.setattr(rendering.threading, "Timer", DummyTimer)

    events: List[Tuple[str, dict]] = []

    def logger(action: str, context: dict) -> None:
        events.append((action, context))

    assert rendering._attempt_prompt_toolkit_pager(
        "line-one",
        ui_event_logger=logger,
        automation_timeout=1.25,
    )

    assert app_registry[-1].exit_called is True
    actions = [action for action, _ in events]
    assert "automation-timeout" in actions
    assert "quit" in actions


def test_prompt_toolkit_replays_automation_key_sequences(monkeypatch) -> None:
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
            self.size = DummySize(20, 6)

        def get_size(self) -> DummySize:
            return self.size

    class DummyTimer:
        def __init__(self, interval, callback) -> None:
            self.interval = interval
            self.callback = callback

        def start(self) -> None:
            self.callback()

        def cancel(self) -> None:
            return

    app_registry: List["DummyApplication"] = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(20, 2)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

    class DummyKeyBindings:
        def __init__(self) -> None:
            self.handlers = {}

        def add(self, *keys, **kwargs):
            def decorator(func):
                for key in keys:
                    self.handlers[key] = func
                return func

            return decorator

    class DummyLayout:
        def __init__(self, container) -> None:
            self.container = container

    class DummyStyle:
        @classmethod
        def from_dict(cls, mapping):
            return mapping

    class DummyEvent:
        def __init__(self, app) -> None:
            self.app = app

    class DummyKeyProcessor:
        def __init__(self, app) -> None:
            self.app = app
            self.pending = []

        def feed_multiple(self, key_presses, first: bool = False) -> None:
            self.pending.extend(list(key_presses))

        def process_keys(self) -> None:
            event = DummyEvent(self.app)
            for key_press in self.pending:
                key = getattr(key_press, "key", key_press)
                resolved = getattr(key, "value", key)
                handler = self.app.key_bindings.handlers.get(str(resolved))
                if handler is not None:
                    handler(event)
            self.pending.clear()

    class DummyApplication:
        def __init__(self, layout, key_bindings, full_screen, style) -> None:
            self.layout = layout
            self.key_bindings = key_bindings
            self.output = DummyOutput()
            self.key_processor = DummyKeyProcessor(self)
            app_registry.append(self)

        def invalidate(self) -> None:
            return

        def exit(self) -> None:
            return

        def run(self) -> None:
            self.layout.container.content.text_func()

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
    monkeypatch.setattr(rendering.threading, "Timer", DummyTimer)

    events: List[Tuple[str, dict]] = []

    def logger(action: str, context: dict) -> None:
        events.append((action, context))

    assert rendering._attempt_prompt_toolkit_pager(
        "line-0\nline-1\nline-2",
        ui_event_logger=logger,
        automation_replay=[(0.0, "down"), (0.0, "m-c-x")],
        viewport_rows=2,
    )

    assert app_registry[-1].layout.container.vertical_scroll == 1
    replay_actions = [
        action for action, _ in events if action == "automation-replay-key"
    ]
    assert len(replay_actions) == 2
    combo_event = next(
        context
        for action, context in events
        if action == "automation-replay-key" and context["key_spec"] == "m-c-x"
    )
    assert combo_event["key_count"] >= 2


def test_prompt_toolkit_replay_zero_delay_without_running_event_loop(
    monkeypatch,
) -> None:
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
            self.size = DummySize(20, 6)

        def get_size(self) -> DummySize:
            return self.size

    class DummyTimer:
        def __init__(self, interval, callback) -> None:
            self.interval = interval
            self.callback = callback

        def start(self) -> None:
            self.callback()

        def cancel(self) -> None:
            return

    app_registry: List["DummyApplication"] = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(20, 2)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

    class DummyKeyBindings:
        def __init__(self) -> None:
            self.handlers = {}

        def add(self, *keys, **kwargs):
            def decorator(func):
                for key in keys:
                    self.handlers[key] = func
                return func

            return decorator

    class DummyLayout:
        def __init__(self, container) -> None:
            self.container = container

    class DummyStyle:
        @classmethod
        def from_dict(cls, mapping):
            return mapping

    class DummyEvent:
        def __init__(self, app) -> None:
            self.app = app

    class DummyKeyProcessor:
        def __init__(self, app) -> None:
            self.app = app
            self.pending = []

        def feed_multiple(self, key_presses, first: bool = False) -> None:
            self.pending.extend(list(key_presses))

        def process_keys(self) -> None:
            event = DummyEvent(self.app)
            for key_press in self.pending:
                key = getattr(key_press, "key", key_press)
                resolved = getattr(key, "value", key)
                handler = self.app.key_bindings.handlers.get(str(resolved))
                if handler is not None:
                    handler(event)
            self.pending.clear()

    class DummyApplication:
        def __init__(self, layout, key_bindings, full_screen, style) -> None:
            self.layout = layout
            self.key_bindings = key_bindings
            self.output = DummyOutput()
            self.key_processor = DummyKeyProcessor(self)
            app_registry.append(self)

        def call_from_executor(self, callback) -> None:
            raise RuntimeError("no running event loop")

        def invalidate(self) -> None:
            return

        def exit(self) -> None:
            return

        def run(self) -> None:
            self.layout.container.content.text_func()

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
    monkeypatch.setattr(rendering.threading, "Timer", DummyTimer)

    assert rendering._attempt_prompt_toolkit_pager(
        "line-0\nline-1\nline-2",
        automation_replay=[(0.0, "down")],
        viewport_rows=2,
    )
    assert app_registry[-1].layout.container.vertical_scroll == 1


def test_prompt_toolkit_timeout_writes_screenshot_artifact(
    monkeypatch, tmp_path: Path
) -> None:
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
            self.size = DummySize(20, 6)

        def get_size(self) -> DummySize:
            return self.size

    class DummyTimer:
        def __init__(self, interval, callback) -> None:
            self.interval = interval
            self.callback = callback

        def start(self) -> None:
            self.callback()

        def cancel(self) -> None:
            return

    app_registry: List["DummyApplication"] = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(20, 6)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

    class DummyKeyBindings:
        def __init__(self) -> None:
            self.handlers = {}

        def add(self, *keys, **kwargs):
            def decorator(func):
                for key in keys:
                    self.handlers[key] = func
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
            self.key_bindings = key_bindings
            self.output = DummyOutput()
            self.exit_called = False
            app_registry.append(self)

        def invalidate(self) -> None:
            return

        def exit(self) -> None:
            self.exit_called = True

        def run(self) -> None:
            self.layout.container.content.text_func()

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
    monkeypatch.setattr(rendering.threading, "Timer", DummyTimer)

    capture_basename = tmp_path / "timeout-capture"
    capture_txt = tmp_path / "timeout-capture.txt"
    capture_attrs = tmp_path / "timeout-capture.attrs.json"
    events: List[Tuple[str, dict]] = []

    def logger(action: str, context: dict) -> None:
        events.append((action, context))

    assert rendering._attempt_prompt_toolkit_pager(
        "line-one\nline-two",
        ui_event_logger=logger,
        automation_timeout=0.5,
        automation_timeout_screenshot_basename=capture_basename,
        viewport_columns=8,
        viewport_rows=3,
    )

    assert capture_txt.read_bytes() == b"line-one\r\nline-two\r\n        \r\n"

    payload = json.loads(capture_attrs.read_text(encoding="utf-8"))
    assert payload["format"] == "mdview-timeout-framebuffer-attrs-v1"
    assert payload["capture_source"] == "synthetic-text-buffer"
    assert payload["viewport_columns"] == 8
    assert payload["viewport_rows"] == 3
    assert payload["rows"][0]["cells"][0]["character_utf8"] == "l"
    assert payload["rows"][0]["cells"][0]["character_ascii"] == "l"
    assert payload["rows"][2]["cells"][7]["character_ascii"] == " "

    actions = [action for action, _ in events]
    assert "automation-timeout-screenshot" in actions
    assert "automation-timeout" in actions
    assert "quit" in actions
    screenshot_events = [
        context
        for action, context in events
        if action == "automation-timeout-screenshot"
    ]
    assert screenshot_events
    assert screenshot_events[0]["txt_path"] == str(capture_txt.resolve())
    assert screenshot_events[0]["attrs_path"] == str(capture_attrs.resolve())
    assert actions.index("automation-timeout-screenshot") < actions.index(
        "automation-timeout"
    )


def test_automation_replay_changes_timeout_capture_viewport(
    monkeypatch, tmp_path: Path
) -> None:
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
            self.size = DummySize(12, 4)

        def get_size(self) -> DummySize:
            return self.size

    class DummyTimer:
        def __init__(self, interval, callback) -> None:
            self.interval = interval
            self.callback = callback

        def start(self) -> None:
            self.callback()

        def cancel(self) -> None:
            return

    app_registry: List["DummyApplication"] = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(12, 4)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

    class DummyKeyBindings:
        def __init__(self) -> None:
            self.handlers = {}

        def add(self, *keys, **kwargs):
            def decorator(func):
                for key in keys:
                    self.handlers[key] = func
                return func

            return decorator

    class DummyLayout:
        def __init__(self, container) -> None:
            self.container = container

    class DummyStyle:
        @classmethod
        def from_dict(cls, mapping):
            return mapping

    class DummyEvent:
        def __init__(self, app) -> None:
            self.app = app

    class DummyKeyProcessor:
        def __init__(self, app) -> None:
            self.app = app
            self.pending = []

        def feed_multiple(self, key_presses, first: bool = False) -> None:
            self.pending.extend(list(key_presses))

        def process_keys(self) -> None:
            event = DummyEvent(self.app)
            for key_press in self.pending:
                key = getattr(key_press, "key", key_press)
                resolved = getattr(key, "value", key)
                handler = self.app.key_bindings.handlers.get(str(resolved))
                if handler is not None:
                    handler(event)
            self.pending.clear()

    class DummyApplication:
        def __init__(self, layout, key_bindings, full_screen, style) -> None:
            self.layout = layout
            self.key_bindings = key_bindings
            self.output = DummyOutput()
            self.key_processor = DummyKeyProcessor(self)
            app_registry.append(self)

        def invalidate(self) -> None:
            return

        def exit(self) -> None:
            return

        def run(self) -> None:
            self.layout.container.content.text_func()

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
    monkeypatch.setattr(rendering.threading, "Timer", DummyTimer)

    sample = "line-00\nline-01\nline-02\nline-03\nline-04\n"
    baseline_base = tmp_path / "baseline"
    moved_base = tmp_path / "moved"

    assert rendering._attempt_prompt_toolkit_pager(
        sample,
        automation_timeout=0.1,
        automation_timeout_screenshot_basename=baseline_base,
        viewport_columns=8,
        viewport_rows=2,
    )
    assert rendering._attempt_prompt_toolkit_pager(
        sample,
        automation_timeout=0.1,
        automation_timeout_screenshot_basename=moved_base,
        viewport_columns=8,
        viewport_rows=2,
        automation_replay=[(0.01, "down")],
    )

    baseline_txt = (tmp_path / "baseline.txt").read_text(encoding="ascii")
    moved_txt = (tmp_path / "moved.txt").read_text(encoding="ascii")
    assert baseline_txt.splitlines()[0].startswith("line-00")
    assert moved_txt.splitlines()[0].startswith("line-01")

    baseline_attrs = json.loads((tmp_path / "baseline.attrs.json").read_text("utf-8"))
    moved_attrs = json.loads((tmp_path / "moved.attrs.json").read_text("utf-8"))
    assert baseline_attrs["vertical_scroll"] == 0
    assert moved_attrs["vertical_scroll"] == 1


def test_prompt_toolkit_timeout_prefers_renderer_framebuffer(
    monkeypatch, tmp_path: Path
) -> None:
    class DummyCell:
        def __init__(self, char: str, style: str = "") -> None:
            self.char = char
            self.style = style

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
            self.size = DummySize(2, 2)

        def get_size(self) -> DummySize:
            return self.size

    class DummyScreen:
        def __init__(self) -> None:
            self.data_buffer = {
                0: {
                    0: DummyCell("A", "fg:#ffffff bg:#000000 bold"),
                    1: DummyCell("B", "fg:#00ff00"),
                },
                1: {0: DummyCell("C")},
            }

    class DummyRenderer:
        def __init__(self) -> None:
            self.last_rendered_screen = DummyScreen()

    class DummyTimer:
        def __init__(self, interval, callback) -> None:
            self.interval = interval
            self.callback = callback

        def start(self) -> None:
            self.callback()

        def cancel(self) -> None:
            return

    app_registry: List["DummyApplication"] = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info: DummyRenderInfo = DummyRenderInfo(2, 2)
            self.vertical_scroll = 0
            self.horizontal_scroll = 0

    class DummyKeyBindings:
        def __init__(self) -> None:
            self.handlers = {}

        def add(self, *keys, **kwargs):
            def decorator(func):
                for key in keys:
                    self.handlers[key] = func
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
            self.key_bindings = key_bindings
            self.output = DummyOutput()
            self.renderer = DummyRenderer()
            app_registry.append(self)

        def invalidate(self) -> None:
            return

        def exit(self) -> None:
            return

        def run(self) -> None:
            self.layout.container.content.text_func()

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
    monkeypatch.setattr(rendering.threading, "Timer", DummyTimer)

    capture_basename = tmp_path / "renderer-capture"
    capture_txt = tmp_path / "renderer-capture.txt"
    capture_attrs = tmp_path / "renderer-capture.attrs.json"

    assert rendering._attempt_prompt_toolkit_pager(
        "ignored",
        automation_timeout=0.1,
        automation_timeout_screenshot_basename=capture_basename,
        viewport_columns=2,
        viewport_rows=2,
    )

    assert capture_txt.read_bytes() == b"AB\r\nC \r\n"

    payload = json.loads(capture_attrs.read_text(encoding="utf-8"))
    assert payload["capture_source"] == "prompt_toolkit-renderer"
    first_cell = payload["rows"][0]["cells"][0]
    assert first_cell["character_utf8"] == "A"
    assert first_cell["attributes"]["foreground"] == "#ffffff"
    assert first_cell["attributes"]["background"] == "#000000"
    assert first_cell["attributes"]["bold"] is True
