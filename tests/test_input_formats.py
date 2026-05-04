from mdview.input_formats import detect_input_format


def test_detect_input_format_recognizes_markdown_heading() -> None:
    detected = detect_input_format("# Heading\n\nBody\n")

    assert detected.name == "markdown"
    assert detected.markdown is True


def test_detect_input_format_recognizes_markdown_table() -> None:
    detected = detect_input_format("| name | score |\n| --- | ---: |\n| Ada | 99 |\n")

    assert detected.name == "markdown"
    assert detected.markdown is True


def test_detect_input_format_falls_back_to_plain_text_for_plain_prose() -> None:
    detected = detect_input_format("plain line one\nplain line two\n")

    assert detected.name == "plain_text"
    assert detected.markdown is False


def test_detect_input_format_falls_back_to_plain_text_for_bad_link() -> None:
    detected = detect_input_format("[broken link](\njust text\n")

    assert detected.name == "plain_text"
    assert detected.markdown is False
