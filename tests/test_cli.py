import importlib

import pytest

from mdview import cli as cli_module


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


def test_main_requires_path_without_verification_flag(capsys):
    exit_code = cli_module.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "path is required" in captured.err


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


def test_format_help_matches_expected_shape():
    help_text = cli_module.format_help()

    assert "usage: mdview" in help_text
    assert "--reflow" in help_text
    assert "--reflow-mode {prose,all,none}" in help_text
    assert "--noreflow" in help_text
    assert "--readability-first-tables" in help_text
    assert "Render Markdown in the terminal" in help_text
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
