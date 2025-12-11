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
