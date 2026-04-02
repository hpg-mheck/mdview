from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_repo_mdview_shim_delegates_to_internal_cli_without_external_renderers():
    shim = (ROOT / "mdview").read_text(encoding="utf-8")

    assert "mdview.cli" in shim
    assert "pandoc" not in shim
    assert "xdg-open" not in shim
    assert ".venv/bin/python" in shim
    assert "PYTHONPATH" in shim
