from pathlib import Path

try:  # pragma: no cover - import fallback only for older runtimes
    from importlib.metadata import metadata
except ImportError:  # pragma: no cover
    from importlib_metadata import metadata  # type: ignore


def test_author_email_is_populated() -> None:
    project_metadata = metadata("mdview")
    author_emails = project_metadata.get_all("Author-email")

    assert author_emails, "Author-email metadata should be populated."
    assert any(
        "mheck@hardproblemsgroup.com" in author_email for author_email in author_emails
    ), "Expected author email missing from metadata."


def test_pyproject_declares_runtime_and_dev_tool_dependencies() -> None:
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert "prompt_toolkit>=3.0" in pyproject
    assert "rich>=13.7.0" in pyproject
    assert "black>=24.0" in pyproject
    assert "pytest>=7.4" in pyproject
    assert "ruff>=0.6.0" in pyproject
