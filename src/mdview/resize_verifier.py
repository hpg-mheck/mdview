"""Interactive workflow for verifying terminal resize event handling.

The verifier walks the user through a series of resize operations, captures
every terminal geometry change, and evaluates whether at least one event in
each burst matches the expectation for the current step. The implementation
intentionally favors clarity over cleverness so that future maintainers can
audit the timing, safety checks, and reporting flow without surprises.
"""

import io
import os
import select
import shutil
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Deque, List, Optional, TextIO, Tuple


class ResizeExpectation(Enum):
    """Enumerate resize expectations for each verification step."""

    NARROWER = "narrower"
    WIDER = "wider"
    TALLER = "taller"
    SHORTER = "shorter"
    INWARD = "inward"
    OUTWARD = "outward"
    MAXIMIZE = "maximize"
    RESTORE = "restore"


@dataclass
class ResizeStep:
    """Describe an interactive resize instruction."""

    name: str
    instruction: str
    expectation: ResizeExpectation
    description: str


@dataclass
class ResizeResult:
    """Record the outcome of a resize verification step."""

    step: ResizeStep
    detected: bool
    passed: bool
    observed_size: Optional[os.terminal_size]
    note: str


class ResizeVerificationReport:
    """Aggregate verification results and format human-readable output."""

    def __init__(self, results: List[ResizeResult]):
        self.results = results

    @property
    def overall_passed(self) -> bool:
        """Return True when every step passed."""

        return all(result.passed for result in self.results)

    def _format_size(self, size: Optional[os.terminal_size]) -> str:
        if size is None:
            return "not detected"
        return f"{size.columns}x{size.lines}"

    def format_table(self) -> str:
        """Render a table summarizing expectations and results.

        The table includes a final overall PASS/FAIL line for at-a-glance
        consumption. Column widths are computed from the data to avoid
        wrapping, which keeps the output readable on narrow terminals.
        """

        headers = ["Step", "Expectation", "Observed", "Result", "Notes"]
        rows: List[List[str]] = []
        for result in self.results:
            rows.append(
                [
                    result.step.name,
                    result.step.description,
                    self._format_size(result.observed_size),
                    "PASS" if result.passed else "FAIL",
                    result.note or "",
                ]
            )
        widths = [
            max(len(header), max((len(row[index]) for row in rows), default=0))
            for index, header in enumerate(headers)
        ]
        header_line = " | ".join(
            header.ljust(width) for header, width in zip(headers, widths)
        )
        separator = "-+-".join("-" * width for width in widths)
        body_lines = [
            " | ".join(value.ljust(width) for value, width in zip(row, widths))
            for row in rows
        ]
        lines = [header_line, separator] + body_lines
        overall = "PASS" if self.overall_passed else "FAIL"
        lines.append("")
        lines.append(f"OVERALL RESULT: {overall}")
        return "\n".join(lines)


class ResizeDetectionVerifier:
    """Guide the user through a resize detection sequence.

    The verifier listens for SIGWINCH signals or polling-based size changes,
    queues every unique geometry, and treats a "quiet period" of two seconds
    without new events as the boundary of a resize attempt. Each step passes
    when at least one event in the collected burst matches the expected
    direction of change. A five-second guardrail fails the step if activity
    never starts or never settles, mirroring an operator who walks away or a
    misbehaving terminal emulator.
    """

    def __init__(
        self,
        *,
        size_reader: Callable[[], os.terminal_size] = shutil.get_terminal_size,
        input_stream: TextIO = sys.stdin,
        output_stream: TextIO = sys.stdout,
        sleep: Callable[[float], None] = time.sleep,
        poll_interval: float = 0.1,
        monotonic: Callable[[], float] = time.monotonic,
        install_signal_handler: bool = True,
    ) -> None:
        self._size_reader = size_reader
        self._input_stream = input_stream
        self._output_stream = output_stream
        self._sleep = sleep
        self._poll_interval = poll_interval
        self._monotonic = monotonic
        self._install_signal_handler = install_signal_handler

        self._pending_sizes: Deque[os.terminal_size] = deque()
        self._initial_size: Optional[os.terminal_size] = None
        self._current_size: Optional[os.terminal_size] = None
        self._max_size: Optional[os.terminal_size] = None
        self._previous_handler = None

        self._steps: List[ResizeStep] = [
            ResizeStep(
                name="Narrower",
                instruction="Make the terminal narrower.",
                expectation=ResizeExpectation.NARROWER,
                description="Width decreases",
            ),
            ResizeStep(
                name="Wider",
                instruction="Make the terminal wider.",
                expectation=ResizeExpectation.WIDER,
                description="Width increases",
            ),
            ResizeStep(
                name="Taller",
                instruction="Make the terminal taller.",
                expectation=ResizeExpectation.TALLER,
                description="Height increases",
            ),
            ResizeStep(
                name="Shorter",
                instruction="Make the terminal shorter.",
                expectation=ResizeExpectation.SHORTER,
                description="Height decreases",
            ),
            ResizeStep(
                name="Lower right corner in",
                instruction="Bring the lower right corner inward.",
                expectation=ResizeExpectation.INWARD,
                description="Width and height decrease",
            ),
            ResizeStep(
                name="Lower right corner out",
                instruction="Push the lower right corner outward.",
                expectation=ResizeExpectation.OUTWARD,
                description="Width and height increase",
            ),
            ResizeStep(
                name="Maximize",
                instruction="Maximize the terminal window.",
                expectation=ResizeExpectation.MAXIMIZE,
                description="Width and height reach new maximums",
            ),
            ResizeStep(
                name="Restore",
                instruction="Restore the terminal to its starting size.",
                expectation=ResizeExpectation.RESTORE,
                description="Width and height return to start",
            ),
        ]

    def notify_resize(self, size: os.terminal_size) -> None:
        """Queue a resize event detected externally.

        The verifier consults this queue before polling the terminal size so
        that signal-driven notifications are processed promptly without
        blocking the main loop.
        """

        if self._current_size is not None and size == self._current_size:
            return
        self._pending_sizes.append(size)

    def run(self) -> ResizeVerificationReport:
        """Execute the verification steps and return the report.

        The method installs a SIGWINCH handler (unless disabled), guides the
        user through eight resize prompts, and summarizes the results in a
        table. Cleanup always restores the previous handler to avoid surprising
        the caller's signal configuration.
        """

        self._initial_size = self._size_reader()
        self._current_size = self._initial_size
        self._max_size = self._initial_size

        if self._install_signal_handler:
            self._previous_handler = signal.getsignal(signal.SIGWINCH)
            signal.signal(signal.SIGWINCH, self._handle_sigwinch)

        try:
            self._write_line("Resize detection verification starting.")
            self._write_line(
                "Press X then Enter if a step does not detect your resize action."
            )
            self._write_line("")

            results: List[ResizeResult] = []
            for step in self._steps:
                results.append(self._run_step(step))

            report = ResizeVerificationReport(results)
            self._write_line("")
            self._write_line(report.format_table())
            return report
        finally:
            if self._install_signal_handler and self._previous_handler is not None:
                signal.signal(signal.SIGWINCH, self._previous_handler)

    def _handle_sigwinch(self, _signum, _frame) -> None:
        try:
            size = self._size_reader()
        except OSError:
            return
        self.notify_resize(size)

    def _run_step(self, step: ResizeStep) -> ResizeResult:
        """Drive a single resize instruction from prompt to evaluation."""
        self._write_line(f"Step: {step.name}")
        self._write_line(f"  Action: {step.instruction}")
        self._write_line(f"  Expectation: {step.description}")

        observed_sizes, user_reported_miss, timed_out = self._await_resize_or_abort()
        if user_reported_miss:
            note = "User reported missed resize detection with X."
            self._write_line(f"  Result: FAIL ({note})")
            return ResizeResult(
                step, detected=False, passed=False, observed_size=None, note=note
            )

        if timed_out:
            if observed_sizes:
                self._record_size(observed_sizes[-1])
            note = "Timed out waiting for resize activity."
            self._write_line(f"  Result: FAIL ({note})")
            return ResizeResult(
                step,
                detected=bool(observed_sizes),
                passed=False,
                observed_size=observed_sizes[-1] if observed_sizes else None,
                note=note,
            )

        if not observed_sizes:
            note = "No resize detected."
            self._write_line(f"  Result: FAIL ({note})")
            return ResizeResult(
                step, detected=False, passed=False, observed_size=None, note=note
            )

        assert self._current_size is not None
        expected_matches = 0
        first_match_note: Optional[str] = None
        previous_size = self._current_size
        for observed_size in observed_sizes:
            passed, note = self._evaluate_step(
                step.expectation, previous_size, observed_size
            )
            if passed:
                expected_matches += 1
                if first_match_note is None:
                    first_match_note = note
            self._record_size(observed_size)
            previous_size = observed_size

        detected = True
        passed = expected_matches > 0
        total_events = len(observed_sizes)
        ratio = expected_matches / total_events
        # The verifier warns when the expected change represents fewer than 70%
        # of the observed events. This keeps the test resilient to stray
        # terminal resize noise while still surfacing suspicious ratios.
        if passed and ratio < 0.7:
            warning = (
                f"\x1b[33mWarning: Only {expected_matches}/{total_events} resize "
                f"events matched the expected {step.expectation.value} change.\x1b[0m"
            )
            self._write_line(warning)

        if passed:
            note = f"{expected_matches}/{total_events} events matched expectation."
            if first_match_note:
                note = f"{note} {first_match_note}"
        else:
            note = "No resize matched the expectation."

        final_size = observed_sizes[-1]
        verdict = "PASS" if passed else "FAIL"
        self._write_line(
            f"  Detected: {final_size.columns}x{final_size.lines} -> {verdict} ({note})"
        )
        return ResizeResult(
            step, detected=detected, passed=passed, observed_size=final_size, note=note
        )

    def _await_resize_or_abort(
        self,
    ) -> Tuple[List[os.terminal_size], bool, bool]:
        """Collect resize events until quiet, an abort signal, or timeout.

        Returns a tuple of three values:
        1. The list of observed sizes in the order they were detected.
        2. A boolean indicating whether the user explicitly reported a miss by
           typing "X" (case-insensitive) followed by Enter.
        3. A boolean indicating whether the wait timed out because activity
           never started or never stopped within five seconds of the step
           beginning.
        """
        start_time = self._monotonic()
        last_event_time: Optional[float] = None
        observed_sizes: List[os.terminal_size] = []
        last_seen_size = self._current_size

        while True:
            next_size = self._dequeue_size_change(last_seen_size)
            if next_size is not None:
                observed_sizes.append(next_size)
                last_seen_size = next_size
                last_event_time = self._monotonic()

            user_signal = self._read_user_signal()
            if user_signal:
                if user_signal.strip().lower().startswith("x"):
                    return observed_sizes, True, False

            now = self._monotonic()
            # Consider the resize attempt complete once two seconds have
            # elapsed without a new event. This allows for multiple quick
            # adjustments while ensuring the step eventually advances.
            if last_event_time is not None and now - last_event_time >= 2.0:
                return observed_sizes, False, False

            # If five seconds pass without any activity or without a quiet
            # period, assume the operator is away or the terminal failed to
            # stabilize. Signal a timeout so the step fails decisively.
            if now - start_time >= 5.0:
                if not last_event_time or now - last_event_time < 2.0:
                    return observed_sizes, False, True

            self._sleep(self._poll_interval)

    def _dequeue_size_change(
        self, reference_size: Optional[os.terminal_size] = None
    ) -> Optional[os.terminal_size]:
        """Return the next resize event or detect a new one via polling."""
        if self._pending_sizes:
            return self._pending_sizes.popleft()

        try:
            current_size = self._size_reader()
        except OSError:
            return None

        comparison_size = reference_size or self._current_size
        if comparison_size is None:
            return None

        if current_size != comparison_size:
            return current_size
        return None

    def _record_size(self, size: os.terminal_size) -> None:
        """Track the latest and maximum terminal sizes seen so far."""
        self._current_size = size
        if self._max_size is None:
            self._max_size = size
            return
        if size.columns > self._max_size.columns or size.lines > self._max_size.lines:
            self._max_size = size

    def _read_user_signal(self) -> Optional[str]:
        """Detect whether the user typed an abort signal without blocking."""
        try:
            fileno = self._input_stream.fileno()
        except (AttributeError, io.UnsupportedOperation, ValueError):
            fileno = None

        if fileno is not None:
            readable, _, _ = select.select([fileno], [], [], 0)
            if readable:
                return self._input_stream.readline()
            return None

        position = None
        try:
            position = self._input_stream.tell()
            data = self._input_stream.readline()
            if data:
                return data
        finally:
            if position is not None:
                self._input_stream.seek(position)
        return None

    def _evaluate_step(
        self,
        expectation: ResizeExpectation,
        previous: os.terminal_size,
        observed: os.terminal_size,
    ) -> Tuple[bool, str]:
        """Assess whether a resize event satisfies the current expectation."""
        assert self._initial_size is not None
        assert self._max_size is not None

        initial = self._initial_size
        max_seen = self._max_size

        if expectation == ResizeExpectation.NARROWER:
            passed = observed.columns < previous.columns
            note = "Width decreased." if passed else "Width did not decrease."
        elif expectation == ResizeExpectation.WIDER:
            passed = observed.columns > previous.columns
            note = "Width increased." if passed else "Width did not increase."
        elif expectation == ResizeExpectation.TALLER:
            passed = observed.lines > previous.lines
            note = "Height increased." if passed else "Height did not increase."
        elif expectation == ResizeExpectation.SHORTER:
            passed = observed.lines < previous.lines
            note = "Height decreased." if passed else "Height did not decrease."
        elif expectation == ResizeExpectation.INWARD:
            passed = (
                observed.columns < previous.columns and observed.lines < previous.lines
            )
            note = (
                "Width and height decreased."
                if passed
                else "Expected both width and height to decrease."
            )
        elif expectation == ResizeExpectation.OUTWARD:
            passed = (
                observed.columns > previous.columns and observed.lines > previous.lines
            )
            note = (
                "Width and height increased."
                if passed
                else "Expected both width and height to increase."
            )
        elif expectation == ResizeExpectation.MAXIMIZE:
            passed = (
                observed.columns >= max_seen.columns
                and observed.lines >= max_seen.lines
            )
            note = "Reached a new maximum size." if passed else "Did not maximize."
        elif expectation == ResizeExpectation.RESTORE:
            tolerance = 2
            width_delta = abs(observed.columns - initial.columns)
            height_delta = abs(observed.lines - initial.lines)
            passed = width_delta <= tolerance and height_delta <= tolerance
            if passed:
                note = "Returned to the starting geometry."
            else:
                note = "Did not return to the starting geometry within tolerance."
        else:  # pragma: no cover - defensive coding for completeness
            passed = False
            note = "Unsupported expectation."

        return passed, note

    def _write_line(self, message: str) -> None:
        self._output_stream.write(f"{message}\n")
        self._output_stream.flush()


__all__ = [
    "ResizeDetectionVerifier",
    "ResizeExpectation",
    "ResizeResult",
    "ResizeStep",
    "ResizeVerificationReport",
]
