"""Standalone terminal input diagnostics for mdview.

Stage 1 uses direct terminal reads with minimal terminal setup so operators can
separate raw input problems from prompt_toolkit behavior. Stage 2 then reuses
the same prompt_toolkit component loader as the main viewer, which makes the
comparison useful when debugging real pager regressions.
"""

import contextlib
from dataclasses import dataclass
from datetime import datetime
import os
import select
import sys
import time
from typing import Callable, List, Optional, TextIO

from mdview.rendering import _prompt_toolkit_components

try:  # pragma: no cover - platform-specific import guard
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows
    termios = None
    tty = None


BAR_WIDTH = 10


@dataclass(frozen=True)
class StageKeyEvent:
    """Represent one normalized diagnostic input event."""

    raw: str
    action: str
    source: str


@dataclass(frozen=True)
class StageResult:
    """Record the outcome of one diagnostic stage."""

    stage: str
    passed: bool
    exit_reason: str
    final_position: int


class DebugRecorder:
    """Capture and emit timestamped debug lines for the diagnostic mode."""

    def __init__(
        self,
        stream: TextIO,
        *,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stream = stream
        self._now = now
        self._monotonic = monotonic
        self._start = monotonic()
        self.entries: List[str] = []
        self._counter = 0

    def mark(self) -> int:
        """Return the current entry count for deferred emission."""

        return len(self.entries)

    def emit_from(self, start_index: int) -> None:
        """Print any recorded entries at or after ``start_index``."""

        for entry in self.entries[start_index:]:
            print(entry, file=self._stream)

    def log(
        self,
        stage: str,
        event_type: str,
        *,
        emit: bool = True,
        **fields: object,
    ) -> str:
        """Record one debug event with wall-clock and elapsed timestamps."""

        timestamp = self._now().isoformat(timespec="milliseconds")
        elapsed = self._monotonic() - self._start
        self._counter += 1
        line = (
            f"{timestamp} +{elapsed:0.3f}s "
            f"#{self._counter:04d} [{stage}] {event_type}"
        )
        if fields:
            ordered = " ".join(
                f"{name}={fields[name]!r}" for name in sorted(fields.keys())
            )
            line = f"{line} {ordered}"
        self.entries.append(line)
        if emit:
            print(line, file=self._stream)
        return line


def _render_feedback_bar(position: int) -> str:
    position = max(0, min(position, BAR_WIDTH - 1))
    cells = ["-"] * BAR_WIDTH
    cells[position] = "|"
    return f"[{''.join(cells)}]"


def _advance_position(position: int, action: str) -> int:
    if action == "left":
        return max(position - 1, 0)
    if action == "right":
        return min(position + 1, BAR_WIDTH - 1)
    return position


def _interpret_posix_stage1_bytes(payload: bytes) -> StageKeyEvent:
    if payload == b"\x1b[D":
        return StageKeyEvent(raw=repr(payload), action="left", source="left-arrow")
    if payload == b"\x1b[C":
        return StageKeyEvent(raw=repr(payload), action="right", source="right-arrow")
    if payload == b",":
        return StageKeyEvent(raw=repr(payload), action="left", source="comma")
    if payload == b".":
        return StageKeyEvent(raw=repr(payload), action="right", source="period")
    if payload in {b"q", b"Q"}:
        return StageKeyEvent(raw=repr(payload), action="quit", source="quit")
    return StageKeyEvent(raw=repr(payload), action="unknown", source="unknown")


def _interpret_windows_stage1_chars(payload: str) -> StageKeyEvent:
    if payload in {"\x00K", "\xe0K"}:
        return StageKeyEvent(raw=repr(payload), action="left", source="left-arrow")
    if payload in {"\x00M", "\xe0M"}:
        return StageKeyEvent(raw=repr(payload), action="right", source="right-arrow")
    if payload == ",":
        return StageKeyEvent(raw=repr(payload), action="left", source="comma")
    if payload == ".":
        return StageKeyEvent(raw=repr(payload), action="right", source="period")
    if payload in {"q", "Q"}:
        return StageKeyEvent(raw=repr(payload), action="quit", source="quit")
    return StageKeyEvent(raw=repr(payload), action="unknown", source="unknown")


def _read_posix_stage1_event(
    input_stream: TextIO,
    *,
    os_read: Callable[[int, int], bytes] = os.read,
    selector: Callable[..., object] = select.select,
    timeout_seconds: float = 0.05,
) -> StageKeyEvent:
    """Read one immediate key event from a POSIX terminal."""

    fd = input_stream.fileno()
    payload = os_read(fd, 1)
    if payload == b"\x1b":
        # Arrow keys arrive as multi-byte escape sequences. Give the terminal a
        # short grace period so Stage 1 can tell the difference between a bare
        # Escape press and a split cursor-key sequence.
        deadline = time.monotonic() + timeout_seconds
        while len(payload) < 8:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = selector([fd], [], [], remaining)
            if not ready:
                break
            chunk = os_read(fd, 1)
            if not chunk:
                break
            payload += chunk
            if payload in {b"\x1b[D", b"\x1b[C"}:
                break
    return _interpret_posix_stage1_bytes(payload)


def _read_windows_stage1_event() -> StageKeyEvent:
    """Read one immediate key event from a Windows terminal."""

    import msvcrt  # pragma: no cover - Windows only

    first = msvcrt.getwch()
    if first in {"\x00", "\xe0"}:
        second = msvcrt.getwch()
        return _interpret_windows_stage1_chars(first + second)
    return _interpret_windows_stage1_chars(first)


@contextlib.contextmanager
def _cbreak_terminal(input_stream: TextIO):
    """Temporarily switch a POSIX terminal into cbreak mode."""

    if termios is None or tty is None:
        yield
        return

    fd = input_stream.fileno()
    original = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)


def _write_line(stream: TextIO, text: str) -> None:
    stream.write(f"{text}\n")
    stream.flush()


def _run_line_oriented_feedback_stage(
    *,
    read_event: Callable[[], StageKeyEvent],
    output_stream: TextIO,
    recorder: DebugRecorder,
    stage_name: str = "stage1",
    stage_title: str = "Stage 1/2",
    initial_position: int = 0,
) -> StageResult:
    """Run the basic line-oriented diagnostic stage."""

    position = max(0, min(initial_position, BAR_WIDTH - 1))
    bar = _render_feedback_bar(position)

    _write_line(output_stream, f"{stage_title}: basic terminal input test.")
    _write_line(
        output_stream,
        "Use Left/Right arrows or ',' and '.' to move the tab to the right.",
    )
    _write_line(output_stream, "Press 'q' to fail this stage and continue.")
    _write_line(output_stream, bar)
    recorder.log(
        stage_name,
        "redraw",
        bar=bar,
        position=position,
        reason="start",
    )

    exit_reason = "quit"
    passed = False

    while True:
        event = read_event()
        before = position
        after = _advance_position(before, event.action)
        recorder.log(
            stage_name,
            "input",
            action=event.action,
            position_after=after,
            position_before=before,
            raw=event.raw,
            source=event.source,
        )

        if event.action == "quit":
            exit_reason = "quit"
            passed = False
            break

        if event.action in {"left", "right"}:
            position = after
            bar = _render_feedback_bar(position)
            _write_line(output_stream, bar)
            recorder.log(
                stage_name,
                "redraw",
                action=event.action,
                bar=bar,
                position=position,
                reason="movement",
            )
            if position >= BAR_WIDTH - 1:
                exit_reason = "completed"
                passed = True
                break

    recorder.log(
        stage_name,
        "result",
        exit_reason=exit_reason,
        final_bar=_render_feedback_bar(position),
        final_position=position,
        passed=passed,
    )
    summary = "PASS" if passed else "FAIL"
    _write_line(
        output_stream,
        f"{stage_title} result: {summary}. Proceeding to Stage 2/2.",
    )
    return StageResult(
        stage=stage_name,
        passed=passed,
        exit_reason=exit_reason,
        final_position=position,
    )


def run_line_oriented_feedback_stage(
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    recorder: DebugRecorder,
) -> StageResult:
    """Run the basic stage with platform-appropriate terminal input setup."""

    try:
        if os.name == "nt":
            return _run_line_oriented_feedback_stage(
                read_event=_read_windows_stage1_event,
                output_stream=output_stream,
                recorder=recorder,
            )
        with _cbreak_terminal(input_stream):
            return _run_line_oriented_feedback_stage(
                read_event=lambda: _read_posix_stage1_event(input_stream),
                output_stream=output_stream,
                recorder=recorder,
            )
    except Exception as error:  # pragma: no cover - defensive runtime guard
        recorder.log(
            "stage1",
            "result",
            exit_reason="setup-failed",
            final_bar=_render_feedback_bar(0),
            final_position=0,
            passed=False,
            error=str(error),
        )
        _write_line(
            output_stream,
            "Stage 1/2 result: FAIL (terminal setup failed). "
            "Proceeding to Stage 2/2.",
        )
        return StageResult(
            stage="stage1",
            passed=False,
            exit_reason="setup-failed",
            final_position=0,
        )


def _describe_prompt_toolkit_event(event: object, fallback_key: str) -> str:
    sequence = getattr(event, "key_sequence", None)
    if not sequence:
        return fallback_key

    parts: List[str] = []
    for key_press in sequence:
        key = getattr(key_press, "key", None)
        data = getattr(key_press, "data", None)
        resolved = getattr(key, "value", key)
        parts.append(f"{resolved!r}/{data!r}")
    return ",".join(parts) if parts else fallback_key


def run_prompt_toolkit_feedback_stage(
    *,
    recorder: DebugRecorder,
) -> StageResult:
    """Run the full-screen prompt_toolkit diagnostic stage."""

    stage_name = "stage2"
    # Full-screen prompt_toolkit redraws and stderr logging do not mix well.
    # Buffer the debug log until the stage exits so the terminal surface the
    # operator is testing is not corrupted by our own diagnostics.
    deferred_start = recorder.mark()
    recorder.log(stage_name, "setup", emit=False, mode="prompt_toolkit")

    components = _prompt_toolkit_components()
    if components is None:
        recorder.log(
            stage_name,
            "result",
            emit=False,
            exit_reason="prompt-toolkit-unavailable",
            final_bar=_render_feedback_bar(0),
            final_position=0,
            passed=False,
        )
        recorder.emit_from(deferred_start)
        return StageResult(
            stage=stage_name,
            passed=False,
            exit_reason="prompt-toolkit-unavailable",
            final_position=0,
        )

    (
        Application,
        KeyBindings,
        Layout,
        Window,
        FormattedTextControl,
        Style,
        get_app,
    ) = components[:7]

    # Mutable state lives in a shared dict so the nested prompt_toolkit
    # callbacks can update it without a long list of ``nonlocal`` statements.
    # Keep the keys explicit; tests and debug logs rely on these names.
    state = {
        "position": 0,
        "last_input": "start",
        "exit_reason": "quit",
        "passed": False,
        "redraw_count": 0,
    }

    def _window_size() -> tuple[Optional[int], Optional[int]]:
        try:
            app = get_app()
            size = app.output.get_size()
            if size is not None:
                width = getattr(size, "columns", None)
                height = getattr(size, "rows", None)
                return width, height
        except (AttributeError, RuntimeError):
            pass

        render_info = window.render_info
        if render_info is None:
            return None, None
        return render_info.window_width, render_info.window_height

    def _log_input(event: object, key_name: str, action: str) -> int:
        before = int(state["position"])
        after = _advance_position(before, action)
        state["position"] = after
        state["last_input"] = key_name
        recorder.log(
            stage_name,
            "input",
            emit=False,
            action=action,
            key=key_name,
            position_after=after,
            position_before=before,
            raw=_describe_prompt_toolkit_event(event, key_name),
        )
        return after

    def formatted_text():
        state["redraw_count"] = int(state["redraw_count"]) + 1
        position = int(state["position"])
        bar = _render_feedback_bar(position)
        width, height = _window_size()
        # Record the geometry observed by prompt_toolkit on each redraw so this
        # stage can be compared directly with the main viewer's resize behavior.
        recorder.log(
            stage_name,
            "redraw",
            emit=False,
            bar=bar,
            height=height,
            last_input=state["last_input"],
            position=position,
            redraw_count=state["redraw_count"],
            width=width,
        )
        return (
            [
                ("class:title", "Stage 2/2: prompt_toolkit input test.\n"),
                (
                    "",
                    "Use Left/Right arrows or ',' and '.' to move the tab to the "
                    "right.\n",
                ),
                ("", "Press 'q' to fail this stage.\n\n"),
                ("", "["),
            ]
            + _build_stage2_bar_segments(position)
            + [
                ("", "]\n"),
                ("", f"Position: {position + 1}/{BAR_WIDTH}\n"),
                ("", f"Last input: {state['last_input']}\n"),
                ("", "Debug log: written to stderr after stage exit.\n"),
            ]
        )

    def _handle_completion(app) -> None:
        # Log the final state before exiting the application so the emitted
        # debug stream shows the same last frame that the operator just saw.
        recorder.log(
            stage_name,
            "result",
            emit=False,
            exit_reason=state["exit_reason"],
            final_bar=_render_feedback_bar(int(state["position"])),
            final_position=int(state["position"]),
            passed=bool(state["passed"]),
        )
        app.exit()

    control = FormattedTextControl(formatted_text, focusable=False, show_cursor=False)
    window = Window(content=control, wrap_lines=False, always_hide_cursor=True)
    bindings = KeyBindings()

    def _move(event, key_name: str, action: str) -> None:
        after = _log_input(event, key_name, action)
        event.app.invalidate()
        if after >= BAR_WIDTH - 1:
            state["passed"] = True
            state["exit_reason"] = "completed"
            _handle_completion(event.app)

    @bindings.add("left")
    def _(event) -> None:  # type: ignore[override]
        _move(event, "left", "left")

    @bindings.add("right")
    def _(event) -> None:  # type: ignore[override]
        _move(event, "right", "right")

    @bindings.add(",")
    def _(event) -> None:  # type: ignore[override]
        _move(event, "comma", "left")

    @bindings.add(".")
    def _(event) -> None:  # type: ignore[override]
        _move(event, "period", "right")

    @bindings.add("q")
    @bindings.add("c-c")
    def _(event) -> None:  # type: ignore[override]
        recorder.log(
            stage_name,
            "input",
            emit=False,
            action="quit",
            key="quit",
            position_after=int(state["position"]),
            position_before=int(state["position"]),
            raw=_describe_prompt_toolkit_event(event, "quit"),
        )
        state["passed"] = False
        state["exit_reason"] = "quit"
        _handle_completion(event.app)

    style = Style.from_dict(
        {
            "title": "bold",
            "bar.marker": "reverse",
        }
    )

    application = Application(
        layout=Layout(window),
        key_bindings=bindings,
        full_screen=True,
        style=style,
    )
    # Match the main viewer's relaxed escape-sequence timing so this stage
    # diagnoses the same high-latency arrow-key behavior instead of an
    # artificially stricter parser configuration.
    application.ttimeoutlen = 1.5
    application.timeoutlen = 1.5

    try:
        application.run()
    except Exception as error:  # pragma: no cover - defensive runtime guard
        state["passed"] = False
        state["exit_reason"] = "application-error"
        recorder.log(
            stage_name,
            "result",
            emit=False,
            exit_reason="application-error",
            final_bar=_render_feedback_bar(int(state["position"])),
            final_position=int(state["position"]),
            passed=False,
            error=str(error),
        )

    recorder.emit_from(deferred_start)
    return StageResult(
        stage=stage_name,
        passed=bool(state["passed"]),
        exit_reason=str(state["exit_reason"]),
        final_position=int(state["position"]),
    )


def _build_stage2_bar_segments(position: int) -> List[tuple[str, str]]:
    segments: List[tuple[str, str]] = []
    for index in range(BAR_WIDTH):
        style = "class:bar.marker" if index == position else ""
        character = "|" if index == position else "-"
        segments.append((style, character))
    return segments


def run_test_input_feedback(
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    debug_stream: TextIO = sys.stderr,
    recorder: Optional[DebugRecorder] = None,
) -> int:
    """Run the multi-stage interactive terminal input diagnostic mode."""

    active_recorder = recorder or DebugRecorder(debug_stream)
    stdin_tty = bool(getattr(input_stream, "isatty", lambda: False)())
    stdout_tty = bool(getattr(output_stream, "isatty", lambda: False)())
    if not stdin_tty or not stdout_tty:
        print(
            "mdview: --test-input-feedback requires interactive TTY stdin/stdout",
            file=debug_stream,
        )
        return 2

    active_recorder.log(
        "mode",
        "setup",
        stdin_tty=stdin_tty,
        stdout_tty=stdout_tty,
    )
    # Always continue into Stage 2, even if Stage 1 fails. The contrast
    # between the raw-input path and the prompt_toolkit path is the main
    # diagnostic value of this mode.
    stage1 = run_line_oriented_feedback_stage(
        input_stream=input_stream,
        output_stream=output_stream,
        recorder=active_recorder,
    )
    active_recorder.log(
        "mode",
        "transition",
        from_stage=stage1.stage,
        reason=stage1.exit_reason,
        to_stage="stage2",
    )
    stage2 = run_prompt_toolkit_feedback_stage(recorder=active_recorder)
    overall_passed = stage1.passed and stage2.passed
    active_recorder.log(
        "mode",
        "result",
        overall_passed=overall_passed,
        stage1_passed=stage1.passed,
        stage2_passed=stage2.passed,
    )
    return 0 if overall_passed else 1


__all__ = [
    "BAR_WIDTH",
    "DebugRecorder",
    "StageKeyEvent",
    "StageResult",
    "_interpret_posix_stage1_bytes",
    "_interpret_windows_stage1_chars",
    "_run_line_oriented_feedback_stage",
    "run_line_oriented_feedback_stage",
    "run_prompt_toolkit_feedback_stage",
    "run_test_input_feedback",
]
