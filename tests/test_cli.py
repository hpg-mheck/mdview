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


def test_build_parser_rejects_abbreviations(capsys):
    parser = cli_module.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--pag", "sample.md"])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "unrecognized arguments: --pag" in captured.err


def test_format_help_matches_expected_shape():
    help_text = cli_module.format_help()

    assert "usage: mdview" in help_text
    assert "--pager COMMAND" in help_text
    assert "Render Markdown in the terminal" in help_text


def test_version_flag_exits_cleanly(capsys):
    parser = cli_module.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["-V"])

    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "mdview" in captured.out
