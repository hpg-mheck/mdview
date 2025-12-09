import importlib
import importlib.util

from mdview import rendering


def test_missing_rich_records_fallback_notice(monkeypatch):
    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name):
        if name == "rich":
            return None
        return original_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    try:
        reloaded = importlib.reload(rendering)
        assert not reloaded.HAS_RICH
        notices = reloaded.get_fallback_notices()
        assert any("Rich not available" in notice for notice in notices)
    finally:
        monkeypatch.setattr(importlib.util, "find_spec", original_find_spec)
        importlib.reload(rendering)


def test_missing_prompt_toolkit_records_notice(monkeypatch):
    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name):
        if name == "prompt_toolkit":
            return None
        return original_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    try:
        reloaded = importlib.reload(rendering)
        reloaded._prompt_toolkit_components()
        notices = reloaded.get_fallback_notices()
        assert any("prompt_toolkit unavailable" in notice for notice in notices)
    finally:
        monkeypatch.setattr(importlib.util, "find_spec", original_find_spec)
        importlib.reload(rendering)
