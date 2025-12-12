"""Deterministic resize verifier tests with explicit timing control."""

import io
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Iterable, Tuple

from mdview.resize_verifier import ResizeDetectionVerifier
from tests.helpers.terminal_simulator import TerminalResizeSimulator


@dataclass
class FakeTimer:
    """Control time progression for deterministic verifier testing.

    The tests use this timer in place of :func:`time.monotonic` so event
    scripts can run instantly without real delays. Advancing time via
    :meth:`advance` allows the scheduler to simulate idle gaps and timeouts in
    a repeatable manner.
    """

    current: float = 0.0

    def monotonic(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@dataclass
class EventScheduler:
    """Emit resize events according to a time-based script.

    Each call to :meth:`sleep` advances the fake clock and, if the next
    scheduled event time is reached, emits exactly one resize event before
    returning. This mirrors the verifier's polling loop, where each sleep
    interval may process at most one signal or poll-triggered geometry change.
    """

    simulator: TerminalResizeSimulator
    verifier: ResizeDetectionVerifier
    timer: FakeTimer
    script: Deque[Tuple[float, int, int]] = field(default_factory=deque)

    def schedule(self, events: Iterable[Tuple[float, int, int]]) -> None:
        for event in events:
            self.script.append(event)

    def sleep(self, seconds: float) -> None:
        target = self.timer.current + seconds
        while self.script and self.script[0][0] <= target:
            event_time, columns, lines = self.script.popleft()
            if self.timer.current < event_time:
                self.timer.advance(event_time - self.timer.current)
            self.simulator.emit_resize(columns, lines, self.verifier)
            return
        if self.timer.current < target:
            self.timer.advance(target - self.timer.current)


def test_resize_verification_sequence_passes() -> None:
    """Happy-path resize run where every step stabilizes and passes."""
    simulator = TerminalResizeSimulator(columns=120, lines=40)
    timer = FakeTimer()
    output = io.StringIO()
    verifier = ResizeDetectionVerifier(
        size_reader=simulator.size_reader,
        input_stream=simulator.input_stream,
        output_stream=output,
        sleep=None,  # type: ignore[arg-type]
        poll_interval=0.5,
        monotonic=timer.monotonic,
        install_signal_handler=False,
    )
    scheduler = EventScheduler(simulator=simulator, verifier=verifier, timer=timer)
    verifier._sleep = scheduler.sleep  # type: ignore[assignment]

    scheduler.schedule(
        [
            (0.5, 100, 40),
            (3.0, 140, 40),
            (5.5, 140, 50),
            (8.0, 140, 30),
            (10.5, 120, 20),
            (13.0, 180, 60),
            (15.5, 200, 70),
            (18.0, 120, 40),
        ]
    )

    report = verifier.run()
    table = report.format_table()

    assert report.overall_passed is True
    assert "OVERALL RESULT: PASS" in table
    assert "Narrower" in table
    assert "Width decreases" in table
    assert "120x40" in table

    log = output.getvalue()
    assert "Step: Narrower" in log
    assert "Step: Restore" in log
    assert "Detected: 120x40 -> PASS" in log


def test_resize_verification_warns_on_mixed_events() -> None:
    """Ensure mixed-event bursts warn but still count as passing."""
    simulator = TerminalResizeSimulator(columns=120, lines=40)
    timer = FakeTimer()
    output = io.StringIO()
    verifier = ResizeDetectionVerifier(
        size_reader=simulator.size_reader,
        input_stream=simulator.input_stream,
        output_stream=output,
        sleep=None,  # type: ignore[arg-type]
        poll_interval=0.5,
        monotonic=timer.monotonic,
        install_signal_handler=False,
    )
    scheduler = EventScheduler(simulator=simulator, verifier=verifier, timer=timer)
    verifier._sleep = scheduler.sleep  # type: ignore[assignment]

    scheduler.schedule(
        [
            (0.5, 100, 40),
            (0.7, 120, 40),
            (1.0, 110, 40),
            (3.5, 140, 40),
            (6.0, 140, 50),
            (8.5, 140, 30),
            (11.0, 120, 20),
            (13.5, 180, 60),
            (16.0, 200, 70),
            (18.5, 120, 40),
        ]
    )

    report = verifier.run()

    assert report.results[0].passed is True
    log = output.getvalue()
    assert "Warning: Only 2/3" in log
    assert "OVERALL RESULT: PASS" in report.format_table()


def test_resize_verification_times_out_without_activity() -> None:
    """Fail a step when no resize activity starts within five seconds."""
    simulator = TerminalResizeSimulator(columns=120, lines=40)
    timer = FakeTimer()
    output = io.StringIO()
    verifier = ResizeDetectionVerifier(
        size_reader=simulator.size_reader,
        input_stream=simulator.input_stream,
        output_stream=output,
        sleep=None,  # type: ignore[arg-type]
        poll_interval=0.5,
        monotonic=timer.monotonic,
        install_signal_handler=False,
    )
    scheduler = EventScheduler(simulator=simulator, verifier=verifier, timer=timer)
    verifier._sleep = scheduler.sleep  # type: ignore[assignment]

    report = verifier.run()

    assert report.results[0].passed is False
    assert report.results[0].note == "Timed out waiting for resize activity."


def test_resize_verification_times_out_when_activity_never_quiets() -> None:
    """Fail when resizes keep firing without a two-second quiet period."""

    simulator = TerminalResizeSimulator(columns=120, lines=40)
    timer = FakeTimer()
    output = io.StringIO()
    verifier = ResizeDetectionVerifier(
        size_reader=simulator.size_reader,
        input_stream=simulator.input_stream,
        output_stream=output,
        sleep=None,  # type: ignore[arg-type]
        poll_interval=0.5,
        monotonic=timer.monotonic,
        install_signal_handler=False,
    )
    scheduler = EventScheduler(simulator=simulator, verifier=verifier, timer=timer)
    verifier._sleep = scheduler.sleep  # type: ignore[assignment]

    # Emit a resize roughly every second so the quiet-period clock never reaches
    # two seconds before the five-second safety cutoff trips.
    scheduler.schedule(
        [
            (0.5, 110, 40),
            (1.5, 100, 40),
            (2.5, 105, 40),
            (3.5, 95, 40),
            (4.5, 90, 40),
        ]
    )

    report = verifier.run()

    assert report.results[0].passed is False
    assert report.results[0].note == "Timed out waiting for resize activity."
