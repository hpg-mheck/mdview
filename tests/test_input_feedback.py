import io
from datetime import datetime, timezone

import mdview.input_feedback as input_feedback


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def make_recorder(stream: io.StringIO) -> input_feedback.DebugRecorder:
    def fixed_now() -> datetime:
        return datetime(2026, 3, 9, 22, 0, 0, tzinfo=timezone.utc)

    def fixed_monotonic() -> float:
        return 100.0

    return input_feedback.DebugRecorder(
        stream,
        now=fixed_now,
        monotonic=fixed_monotonic,
    )


def test_interpret_posix_stage1_bytes_supports_arrows_and_punctuation() -> None:
    assert input_feedback._interpret_posix_stage1_bytes(b"\x1b[D").action == "left"
    assert input_feedback._interpret_posix_stage1_bytes(b"\x1b[C").action == "right"
    assert input_feedback._interpret_posix_stage1_bytes(b",").source == "comma"
    assert input_feedback._interpret_posix_stage1_bytes(b".").source == "period"
    assert input_feedback._interpret_posix_stage1_bytes(b"q").action == "quit"


def test_run_line_oriented_feedback_stage_passes_on_right_edge() -> None:
    events = [
        input_feedback.StageKeyEvent(raw="'period'", action="right", source="period")
        for _ in range(input_feedback.BAR_WIDTH - 1)
    ]
    output_stream = io.StringIO()
    debug_stream = io.StringIO()
    recorder = make_recorder(debug_stream)

    def read_event() -> input_feedback.StageKeyEvent:
        return events.pop(0)

    result = input_feedback._run_line_oriented_feedback_stage(
        read_event=read_event,
        output_stream=output_stream,
        recorder=recorder,
    )

    assert result.passed is True
    assert result.exit_reason == "completed"
    assert result.final_position == input_feedback.BAR_WIDTH - 1
    assert "[---------|]" in output_stream.getvalue()
    debug_text = debug_stream.getvalue()
    assert "[stage1] input" in debug_text
    assert "[stage1] redraw" in debug_text
    assert "[stage1] result" in debug_text


def test_run_line_oriented_feedback_stage_fails_on_quit() -> None:
    output_stream = io.StringIO()
    debug_stream = io.StringIO()
    recorder = make_recorder(debug_stream)

    result = input_feedback._run_line_oriented_feedback_stage(
        read_event=lambda: input_feedback.StageKeyEvent(
            raw="'q'",
            action="quit",
            source="quit",
        ),
        output_stream=output_stream,
        recorder=recorder,
    )

    assert result.passed is False
    assert result.exit_reason == "quit"
    assert "FAIL" in output_stream.getvalue()
    assert "exit_reason='quit'" in debug_stream.getvalue()


def test_run_test_input_feedback_requires_tty() -> None:
    debug_stream = io.StringIO()
    exit_code = input_feedback.run_test_input_feedback(debug_stream=debug_stream)

    assert exit_code == 2
    assert "requires interactive TTY" in debug_stream.getvalue()


def test_run_test_input_feedback_runs_stage2_after_stage1_failure(
    monkeypatch,
) -> None:
    calls = []

    def fake_stage1(**kwargs):
        calls.append("stage1")
        return input_feedback.StageResult(
            stage="stage1",
            passed=False,
            exit_reason="quit",
            final_position=0,
        )

    def fake_stage2(**kwargs):
        calls.append("stage2")
        return input_feedback.StageResult(
            stage="stage2",
            passed=True,
            exit_reason="completed",
            final_position=input_feedback.BAR_WIDTH - 1,
        )

    monkeypatch.setattr(
        input_feedback,
        "run_line_oriented_feedback_stage",
        fake_stage1,
    )
    monkeypatch.setattr(
        input_feedback,
        "run_prompt_toolkit_feedback_stage",
        fake_stage2,
    )

    exit_code = input_feedback.run_test_input_feedback(
        input_stream=TtyBuffer(),
        output_stream=TtyBuffer(),
        debug_stream=io.StringIO(),
    )

    assert exit_code == 1
    assert calls == ["stage1", "stage2"]


def test_prompt_toolkit_feedback_stage_passes_with_arrow_and_punctuation(
    monkeypatch,
) -> None:
    class DummySize:
        def __init__(self, columns: int, rows: int) -> None:
            self.columns = columns
            self.rows = rows

    class DummyOutput:
        def get_size(self) -> DummySize:
            return DummySize(40, 8)

    app_registry = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info = None

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
            self.exited = False
            app_registry.append(self)

        def invalidate(self) -> None:
            self.layout.container.content.text_func()

        def exit(self) -> None:
            self.exited = True

        def run(self) -> None:
            event = DummyEvent(self)
            self.layout.container.content.text_func()
            self.key_bindings.handlers["."](event)
            self.key_bindings.handlers[","](event)
            for _ in range(input_feedback.BAR_WIDTH - 1):
                self.key_bindings.handlers["right"](event)
                if self.exited:
                    break

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

    monkeypatch.setattr(input_feedback, "_prompt_toolkit_components", fake_components)

    debug_stream = io.StringIO()
    recorder = make_recorder(debug_stream)
    result = input_feedback.run_prompt_toolkit_feedback_stage(recorder=recorder)

    assert result.passed is True
    assert result.exit_reason == "completed"
    assert result.final_position == input_feedback.BAR_WIDTH - 1
    debug_text = debug_stream.getvalue()
    assert "[stage2] redraw" in debug_text
    assert "key='period'" in debug_text
    assert "key='comma'" in debug_text
    assert "exit_reason='completed'" in debug_text


def test_prompt_toolkit_feedback_stage_fails_on_quit(monkeypatch) -> None:
    class DummySize:
        def __init__(self, columns: int, rows: int) -> None:
            self.columns = columns
            self.rows = rows

    class DummyOutput:
        def get_size(self) -> DummySize:
            return DummySize(40, 8)

    app_registry = []

    class DummyFormattedTextControl:
        def __init__(self, text, **_: object) -> None:
            self.text_func = text

    class DummyWindow:
        def __init__(self, content, **_: object) -> None:
            self.content = content
            self.render_info = None

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
            self.exited = False
            app_registry.append(self)

        def invalidate(self) -> None:
            self.layout.container.content.text_func()

        def exit(self) -> None:
            self.exited = True

        def run(self) -> None:
            event = DummyEvent(self)
            self.layout.container.content.text_func()
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

    monkeypatch.setattr(input_feedback, "_prompt_toolkit_components", fake_components)

    debug_stream = io.StringIO()
    recorder = make_recorder(debug_stream)
    result = input_feedback.run_prompt_toolkit_feedback_stage(recorder=recorder)

    assert result.passed is False
    assert result.exit_reason == "quit"
    assert "action='quit'" in debug_stream.getvalue()
