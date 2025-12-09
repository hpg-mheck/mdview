import importlib

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
