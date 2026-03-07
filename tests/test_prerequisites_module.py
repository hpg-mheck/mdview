import importlib

from mdview import prerequisites


def test_detect_prerequisite_issues_reports_missing(monkeypatch):
    original_find_spec = importlib.util.find_spec

    def _fake_find_spec(name):
        if name in {"prompt_toolkit", "rich"}:
            return None
        return original_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)
    monkeypatch.setattr(prerequisites.shutil, "which", lambda command: None)

    issues = prerequisites.detect_prerequisite_issues()

    assert any("prompt_toolkit" in issue for issue in issues)
    assert any("rich" in issue for issue in issues)
    assert any("less" in issue for issue in issues)


def test_detect_prerequisite_issues_when_present(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(prerequisites.shutil, "which", lambda command: "/usr/bin/less")

    assert prerequisites.detect_prerequisite_issues() == []
