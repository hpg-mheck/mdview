"""Test harness utilities for simulating terminal resize events."""

import io
import os
from typing import Optional


class TerminalResizeSimulator:
    """Simulate a terminal that can emit resize events."""

    def __init__(self, columns: int = 120, lines: int = 40) -> None:
        self._current_size = os.terminal_size((columns, lines))
        self.input_stream: io.StringIO = io.StringIO()
        self.output_stream: io.StringIO = io.StringIO()

    def size_reader(self) -> os.terminal_size:
        """Return the current simulated size."""

        return self._current_size

    def emit_resize(self, columns: int, lines: int, verifier) -> os.terminal_size:
        """Emit a resize event to the verifier and update stored geometry."""

        self._current_size = os.terminal_size((columns, lines))
        verifier.notify_resize(self._current_size)
        return self._current_size

    def feed_input(self, text: str) -> None:
        """Load simulated user input into the input stream."""

        position: Optional[int] = self.input_stream.tell()
        remaining = self.input_stream.read()
        self.input_stream = io.StringIO(text + remaining)
        if position is not None:
            self.input_stream.seek(0)
