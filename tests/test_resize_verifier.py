import io

from mdview.resize_verifier import ResizeDetectionVerifier
from tests.helpers.terminal_simulator import TerminalResizeSimulator


def test_resize_verification_sequence_passes() -> None:
    simulator = TerminalResizeSimulator(columns=120, lines=40)
    output = io.StringIO()
    verifier = ResizeDetectionVerifier(
        size_reader=simulator.size_reader,
        input_stream=simulator.input_stream,
        output_stream=output,
        sleep=lambda _: None,
        poll_interval=0.0,
        install_signal_handler=False,
    )

    simulator.emit_resize(100, 40, verifier)
    simulator.emit_resize(140, 40, verifier)
    simulator.emit_resize(140, 50, verifier)
    simulator.emit_resize(140, 30, verifier)
    simulator.emit_resize(120, 20, verifier)
    simulator.emit_resize(180, 60, verifier)
    simulator.emit_resize(200, 70, verifier)
    simulator.emit_resize(120, 40, verifier)

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
