import importlib
import io
import os
from pathlib import Path
import threading

import pytest

from mdview import cli as cli_module


class _BlockingTextStream:
    def __init__(self, chunks: list[str] | None = None) -> None:
        self._chunks = list(chunks or [])
        self._condition = threading.Condition()
        self._closed = False
        self.encoding = "utf-8"
        self.errors = "strict"

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise io.UnsupportedOperation("blocking test stream has no fileno")

    def read(self, _size: int = -1) -> str:
        with self._condition:
            while not self._chunks and not self._closed:
                self._condition.wait()
            if self._chunks:
                return self._chunks.pop(0)
            return ""

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class _TtyOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_main_reports_rendering_fallback_notice(monkeypatch, tmp_path, capsys):
    original_find_spec = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    import mdview.rendering as rendering

    try:
        rendering = importlib.reload(rendering)
        cli = importlib.reload(cli_module)
        doc = tmp_path / "sample.md"
        doc.write_text("# Title\n\nBody")

        exit_code = cli.main([str(doc)])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "fallback" in captured.err.lower()
        assert "rich" in captured.err
    finally:
        monkeypatch.setattr(importlib.util, "find_spec", original_find_spec)
        importlib.reload(rendering)
        importlib.reload(cli_module)


def test_main_warns_about_missing_prerequisites(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_module, "detect_prerequisite_issues", lambda: ["prompt_toolkit missing"]
    )
    monkeypatch.setattr(
        cli_module, "report_prerequisite_issues", cli_module.report_prerequisite_issues
    )

    with pytest.raises(SystemExit):
        cli_module.main(["--help"])

    captured = capsys.readouterr()
    assert "prompt_toolkit missing" in captured.err
    assert "environment checks" in captured.err


def test_main_requires_path_without_verification_flag(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_module, "_stdin_supports_buffered_document", lambda input_stream=None: False
    )
    exit_code = cli_module.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "at least one path or buffered stdin input is required" in captured.err


def test_build_parser_rejects_abbreviations(capsys):
    parser = cli_module.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--pag", "sample.md"])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "unrecognized arguments: --pag" in captured.err


def test_main_runs_resize_verifier(monkeypatch):
    class DummyReport:
        overall_passed = True

        @staticmethod
        def format_table():
            return "table"

    class DummyVerifier:
        def run(self):
            return DummyReport()

    monkeypatch.setattr(cli_module, "ResizeDetectionVerifier", lambda: DummyVerifier())

    exit_code = cli_module.main(["--verify-resize-detection"])

    assert exit_code == 0


def test_main_runs_test_input_feedback_mode(monkeypatch):
    captured = {"called": False}

    def fake_runner() -> int:
        captured["called"] = True
        return 1

    monkeypatch.setattr(cli_module, "run_test_input_feedback", fake_runner)

    exit_code = cli_module.main(["--test-input-feedback"])

    assert exit_code == 1
    assert captured["called"] is True


def test_format_help_matches_expected_shape():
    help_text = cli_module.format_help()

    assert "usage: mdview" in help_text
    assert "--reflow" in help_text
    assert "--reflow-mode {prose,all,none}" in help_text
    assert "--noreflow" in help_text
    assert "--verbose" in help_text
    assert "--stdin-timeout-in-seconds" in help_text
    assert "--max-stdin-buffer-megabytes" in help_text
    assert "--MIL" in help_text
    assert "--readability-first-tables" in help_text
    assert "--no-table-borders" in help_text
    assert "--no-cell-borders" in help_text
    assert "--automation-timeout" in help_text
    assert "--automation-timeout-screenshot" in help_text
    assert "--screen-dump-dir" in help_text
    assert "--automation-json" in help_text
    assert "--viewport-columns" in help_text
    assert "--viewport-rows" in help_text
    assert "--redraw-check-digit" in help_text
    assert "--test-input-feedback" in help_text
    assert "Render Markdown or plain text in the terminal" in help_text
    assert "stdin" in help_text
    assert "buffered document" in help_text
    assert "--verify-resize-detection" in help_text


def test_version_flag_exits_cleanly(capsys):
    parser = cli_module.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["-V"])

    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "mdview" in captured.out


def test_resolve_reflow_mode_precedence():
    assert (
        cli_module.resolve_reflow_mode(
            markdown=False,
            reflow=True,
            reflow_mode=None,
            noreflow=False,
        )
        == "prose"
    )
    assert (
        cli_module.resolve_reflow_mode(
            markdown=False,
            reflow=False,
            reflow_mode="all",
            noreflow=False,
        )
        == "all"
    )
    assert (
        cli_module.resolve_reflow_mode(
            markdown=False,
            reflow=True,
            reflow_mode="all",
            noreflow=True,
        )
        == "none"
    )
    assert (
        cli_module.resolve_reflow_mode(
            markdown=True,
            reflow=False,
            reflow_mode=None,
            noreflow=False,
        )
        == "prose"
    )
    assert (
        cli_module.resolve_reflow_mode(
            markdown=False,
            reflow=False,
            reflow_mode=None,
            noreflow=False,
        )
        == "none"
    )


def test_main_exposes_switch_callback_for_multiple_documents(monkeypatch, tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("# First\n\none")
    second.write_text("# Second\n\ntwo")

    captured = {}

    def fake_page_text(text: str, **kwargs):
        captured["initial"] = text
        switch_document = kwargs["switch_document"]
        assert switch_document is not None
        switched = switch_document(1, 80)
        assert switched is not None
        captured["switched"] = switched

    monkeypatch.setattr(cli_module, "page_text", fake_page_text)

    exit_code = cli_module.main([str(first), str(second)])

    assert exit_code == 0
    assert "First" in captured["initial"]
    assert "Second" in captured["switched"]


def test_main_verbose_reports_document_switch(monkeypatch, tmp_path, capsys):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("# First\n\none")
    second.write_text("# Second\n\ntwo")

    def fake_page_text(text: str, **kwargs):
        switch_document = kwargs["switch_document"]
        assert switch_document is not None
        _ = switch_document(1, 100)

    monkeypatch.setattr(cli_module, "page_text", fake_page_text)

    exit_code = cli_module.main(["--verbose", str(first), str(second)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "switched to [2/2]" in captured.err


def test_parser_rejects_negative_automation_timeout(capsys):
    parser = cli_module.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--automation-timeout", "-1", "sample.md"])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "automation timeout must be a non-negative finite number" in captured.err


def test_main_passes_automation_timeout_to_page_text(monkeypatch, tmp_path):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")
    captured = {}

    def fake_page_text(text: str, **kwargs):
        captured["timeout"] = kwargs.get("automation_timeout")
        captured["screenshot_basename"] = kwargs.get(
            "automation_timeout_screenshot_basename"
        )

    monkeypatch.setattr(cli_module, "page_text", fake_page_text)

    exit_code = cli_module.main(["--automation-timeout", "3.5", str(document)])

    assert exit_code == 0
    assert captured["timeout"] == 3.5
    assert captured["screenshot_basename"] == cli_module.Path(
        "mdview-automation-timeout-framebuffer"
    )


def test_main_passes_screen_dump_dir_to_page_text(monkeypatch, tmp_path):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")
    capture_dir = tmp_path / "captures"
    captured = {}

    def fake_page_text(text: str, **kwargs):
        captured["screen_dump_dir"] = kwargs.get("screen_dump_dir")

    monkeypatch.setattr(cli_module, "page_text", fake_page_text)

    exit_code = cli_module.main(
        [
            "--screen-dump-dir",
            str(capture_dir),
            str(document),
        ]
    )

    assert exit_code == 0
    assert captured["screen_dump_dir"] == capture_dir


def test_parse_automation_json_source_accepts_literal_json() -> None:
    events = cli_module._parse_automation_json_source(
        '[[0.0, "down"], [0.25, "m-c-x"]]'
    )
    assert events == [(0.0, "down"), (0.25, "m-c-x")]


def test_parse_automation_json_source_reads_file(tmp_path: Path) -> None:
    source = tmp_path / "events.json"
    source.write_text('[[0.0, "down"], [1, "pagedown"]]', encoding="utf-8")

    events = cli_module._parse_automation_json_source(str(source))
    assert events == [(0.0, "down"), (1.0, "pagedown")]


def test_parse_automation_json_source_rejects_invalid_schema() -> None:
    with pytest.raises(ValueError):
        cli_module._parse_automation_json_source('{"delay": 1.0, "key": "down"}')


def test_main_passes_automation_replay_to_page_text(monkeypatch, tmp_path):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")
    captured = {}

    def fake_page_text(text: str, **kwargs):
        captured["automation_replay"] = kwargs.get("automation_replay")

    monkeypatch.setattr(cli_module, "page_text", fake_page_text)

    exit_code = cli_module.main(
        [
            "--automation-json",
            '[[0.0, "down"], [0.5, "pageup"]]',
            str(document),
        ]
    )

    assert exit_code == 0
    assert captured["automation_replay"] == [(0.0, "down"), (0.5, "pageup")]


def test_main_rejects_invalid_automation_json(tmp_path, capsys):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")

    exit_code = cli_module.main(["--automation-json", "not-json", str(document)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "invalid automation JSON" in captured.err


def test_main_rejects_timeout_screenshot_without_timeout(tmp_path, capsys):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")

    exit_code = cli_module.main(
        [
            "--automation-timeout-screenshot",
            "capture",
            str(document),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert (
        "--automation-timeout-screenshot requires --automation-timeout" in captured.err
    )


def test_main_rejects_screen_dump_dir_when_path_is_not_directory(tmp_path, capsys):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")
    output_file = tmp_path / "capture.txt"
    output_file.write_text("not a directory", encoding="utf-8")

    exit_code = cli_module.main(
        [
            "--screen-dump-dir",
            str(output_file),
            str(document),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--screen-dump-dir must name a directory" in captured.err


def test_main_rejects_test_input_feedback_with_paths(tmp_path, capsys):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")

    exit_code = cli_module.main(["--test-input-feedback", str(document)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--test-input-feedback does not accept document paths" in captured.err


def test_main_rejects_special_mode_combination(capsys):
    exit_code = cli_module.main(["--verify-resize-detection", "--test-input-feedback"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "cannot be used together" in captured.err


def test_main_passes_viewport_overrides_to_page_text(monkeypatch, tmp_path):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")
    captured = {}

    def fake_page_text(text: str, **kwargs):
        captured["columns"] = kwargs.get("viewport_columns")
        captured["rows"] = kwargs.get("viewport_rows")

    monkeypatch.setattr(cli_module, "page_text", fake_page_text)

    exit_code = cli_module.main(
        [
            "--viewport-columns",
            "120",
            "--viewport-rows",
            "33",
            str(document),
        ]
    )

    assert exit_code == 0
    assert captured["columns"] == 120
    assert captured["rows"] == 33


def test_main_passes_redraw_check_digit_to_page_text(monkeypatch, tmp_path):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")
    captured = {}

    def fake_page_text(text: str, **kwargs):
        captured["redraw_check_digit"] = kwargs.get("redraw_check_digit")

    monkeypatch.setattr(cli_module, "page_text", fake_page_text)

    exit_code = cli_module.main(["--redraw-check-digit", str(document)])

    assert exit_code == 0
    assert captured["redraw_check_digit"] is True


def test_main_uses_terminal_width_for_initial_render(monkeypatch, tmp_path):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")
    captured = {"widths": []}

    def fake_render_to_ansi(content: str, markdown: bool, **kwargs):
        captured["widths"].append(kwargs.get("width"))
        return "rendered"

    monkeypatch.setattr(cli_module.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        cli_module.shutil,
        "get_terminal_size",
        lambda: os.terminal_size((72, 24)),
    )
    monkeypatch.setattr(cli_module, "render_to_ansi", fake_render_to_ansi)
    monkeypatch.setattr(cli_module, "page_text", lambda text, **kwargs: None)

    exit_code = cli_module.main([str(document)])

    assert exit_code == 0
    assert captured["widths"] == [72]


def test_main_uses_viewport_columns_for_initial_render(monkeypatch, tmp_path):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")
    captured = {"widths": []}

    def fake_render_to_ansi(content: str, markdown: bool, **kwargs):
        captured["widths"].append(kwargs.get("width"))
        return "rendered"

    monkeypatch.setattr(cli_module.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        cli_module.shutil,
        "get_terminal_size",
        lambda: os.terminal_size((40, 24)),
    )
    monkeypatch.setattr(cli_module, "render_to_ansi", fake_render_to_ansi)
    monkeypatch.setattr(cli_module, "page_text", lambda text, **kwargs: None)

    exit_code = cli_module.main(
        [
            "--viewport-columns",
            "120",
            str(document),
        ]
    )

    assert exit_code == 0
    assert captured["widths"] == [120]


def test_main_passes_table_border_flags_to_render_calls(monkeypatch, tmp_path):
    document = tmp_path / "sample.md"
    document.write_text("# Title\n\nbody")
    captured = []

    def fake_render_to_ansi(content: str, markdown: bool, **kwargs):
        captured.append(
            (
                kwargs.get("table_borders"),
                kwargs.get("cell_borders"),
            )
        )
        return "rendered"

    def fake_page_text(text: str, **kwargs):
        render_on_resize = kwargs["render_on_resize"]
        assert render_on_resize is not None
        _ = render_on_resize(88)

    monkeypatch.setattr(cli_module, "render_to_ansi", fake_render_to_ansi)
    monkeypatch.setattr(cli_module, "page_text", fake_page_text)

    exit_code = cli_module.main(
        [
            "--no-table-borders",
            "--no-cell-borders",
            str(document),
        ]
    )

    assert exit_code == 0
    assert captured == [(False, False), (False, False)]


def test_parser_rejects_non_positive_viewport_columns(capsys):
    parser = cli_module.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--viewport-columns", "0", "sample.md"])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "value must be a positive integer" in captured.err


def test_parser_rejects_non_positive_viewport_rows(capsys):
    parser = cli_module.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--viewport-rows", "-5", "sample.md"])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "value must be a positive integer" in captured.err


def test_main_accepts_buffered_markdown_stdin_without_paths(monkeypatch):
    captured = {}

    def fake_render_to_ansi(content: str, markdown: bool, **kwargs):
        captured["content"] = content
        captured["markdown"] = markdown
        captured["reflow_mode"] = kwargs["reflow_mode"]
        return "rendered"

    def fake_page_text(text: str, **kwargs):
        captured["paged_text"] = text
        captured["prefer_tty_input"] = kwargs["prefer_tty_input"]

    monkeypatch.setattr(cli_module, "render_to_ansi", fake_render_to_ansi)
    monkeypatch.setattr(cli_module, "page_text", fake_page_text)
    monkeypatch.setattr(
        cli_module, "_stdin_supports_buffered_document", lambda input_stream=None: True
    )
    monkeypatch.setattr(
        cli_module,
        "_buffer_stdin_document",
        lambda **kwargs: cli_module._BufferedStdinResult(
            content="# Title\n\nBody\n",
            detected_format=cli_module.DetectedInputFormat(
                name="markdown",
                markdown=True,
            ),
            timed_out=False,
            final_status_line=cli_module._STDIN_BUFFERING_COMPLETE_STATUS,
        ),
    )

    assert cli_module.main([]) == 0
    assert captured["content"] == "# Title\n\nBody\n"
    assert captured["markdown"] is True
    assert captured["reflow_mode"] == "prose"
    assert captured["paged_text"] == "rendered"
    assert captured["prefer_tty_input"] is True


def test_main_accepts_buffered_plain_text_stdin_without_paths(monkeypatch):
    captured = {}

    def fake_render_to_ansi(content: str, markdown: bool, **kwargs):
        captured["content"] = content
        captured["markdown"] = markdown
        captured["reflow_mode"] = kwargs["reflow_mode"]
        return "rendered"

    def fake_page_text(text: str, **kwargs):
        captured["paged_text"] = text
        captured["prefer_tty_input"] = kwargs["prefer_tty_input"]

    monkeypatch.setattr(cli_module, "render_to_ansi", fake_render_to_ansi)
    monkeypatch.setattr(cli_module, "page_text", fake_page_text)
    monkeypatch.setattr(
        cli_module, "_stdin_supports_buffered_document", lambda input_stream=None: True
    )
    monkeypatch.setattr(
        cli_module,
        "_buffer_stdin_document",
        lambda **kwargs: cli_module._BufferedStdinResult(
            content="plain line one\nplain line two\n",
            detected_format=cli_module.DetectedInputFormat(
                name="plain_text",
                markdown=False,
            ),
            timed_out=False,
            final_status_line=cli_module._STDIN_BUFFERING_COMPLETE_STATUS,
        ),
    )

    assert cli_module.main([]) == 0
    assert captured["content"] == "plain line one\nplain line two\n"
    assert captured["markdown"] is False
    assert captured["reflow_mode"] == "none"
    assert captured["paged_text"] == "rendered"
    assert captured["prefer_tty_input"] is True


def test_buffer_stdin_document_reports_complete_status():
    output = _TtyOutput()
    result = cli_module._buffer_stdin_document(
        input_stream=io.StringIO("# Heading\n"),
        output_stream=output,
        idle_timeout_seconds=0.01,
    )

    assert result is not None
    assert result.content == "# Heading\n"
    assert result.detected_format.markdown is True
    assert result.final_status_line == cli_module._STDIN_BUFFERING_COMPLETE_STATUS
    assert output.getvalue() == (
        "Buffering stdin...\n" "\x1b[1F\x1b[2KBuffering stdin... complete.\n"
    )


def test_buffer_stdin_document_reports_timeout_status():
    stream = _BlockingTextStream(["partial"])
    output = _TtyOutput()
    result = cli_module._buffer_stdin_document(
        input_stream=stream,
        output_stream=output,
        idle_timeout_seconds=0.01,
    )

    assert result is not None
    assert result.content == "partial"
    assert result.timed_out is True
    assert result.final_status_line == cli_module._STDIN_BUFFERING_TIMEOUT_STATUS
    assert output.getvalue() == (
        "Buffering stdin...\n"
        "\x1b[1F\x1b[2KBuffering stdin... giving up after timeout\n"
    )


def test_buffer_stdin_document_returns_none_when_no_bytes_arrive():
    stream = _BlockingTextStream()
    output = _TtyOutput()
    result = cli_module._buffer_stdin_document(
        input_stream=stream,
        output_stream=output,
        idle_timeout_seconds=0.01,
    )

    assert result is None
    assert output.getvalue() == ""


def test_read_buffered_stdin_content_reads_until_eof():
    result = cli_module._read_buffered_stdin_content(
        input_stream=_BlockingTextStream(["hello ", "world", ""]),
        idle_timeout_seconds=0.01,
    )

    assert result.content == "hello world"
    assert result.received_data is True
    assert result.timed_out is False


def test_read_buffered_stdin_content_stops_after_idle_timeout():
    stream = _BlockingTextStream(["partial"])
    result = cli_module._read_buffered_stdin_content(
        input_stream=stream,
        idle_timeout_seconds=0.01,
    )
    stream.close()

    assert result.content == "partial"
    assert result.received_data is True
    assert result.timed_out is True


def test_read_buffered_stdin_content_rejects_oversize_input():
    with pytest.raises(cli_module._StdinBufferLimitExceeded):
        cli_module._read_buffered_stdin_content(
            input_stream=io.StringIO("abcdef"),
            idle_timeout_seconds=0.01,
            max_buffer_bytes=3,
        )
