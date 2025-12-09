import importlib.util
import json

from mdview import iteration_exit


def test_detect_dependencies_reports_missing(monkeypatch):
    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name):
        if name == "rich":
            return None
        return original_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    statuses = iteration_exit.detect_dependencies()
    status_by_name = {status.name: status for status in statuses}

    assert not status_by_name["rich"].available
    assert "prompt_toolkit" in status_by_name
    assert status_by_name["prompt_toolkit"].description.startswith("prompt_toolkit")


def test_run_iteration_exit_suite_emits_warnings(monkeypatch, capsys):
    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name):
        if name in {"rich", "prompt_toolkit"}:
            return None
        return original_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    received_args = []

    def fake_pytest_runner(args):
        received_args.extend(args)
        return 0

    report = iteration_exit.run_iteration_exit_suite(pytest_runner=fake_pytest_runner)

    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert str(iteration_exit.SUITE_PATH) in received_args[0]
    assert report.exit_code == 0
    assert {status.name for status in report.missing_dependencies} == {
        "rich",
        "prompt_toolkit",
    }


def test_write_summary_serializes_report(tmp_path):
    report = iteration_exit.IterationExitReport(
        exit_code=1,
        missing_dependencies=[
            iteration_exit.DependencyStatus(
                name="rich",
                description="Rich-based Markdown rendering and styling",
                available=False,
            )
        ],
        warnings=[
            "rich unavailable: falling back from Rich-based Markdown rendering and styling."
        ],
        report_file=None,
    )

    destination = tmp_path / "summary.json"
    iteration_exit.write_summary(report, destination)

    content = json.loads(destination.read_text())
    assert content["exit_code"] == 1
    assert content["missing_dependencies"] == [
        {"name": "rich", "description": "Rich-based Markdown rendering and styling"}
    ]
    assert "rich unavailable" in content["warnings"][0]
