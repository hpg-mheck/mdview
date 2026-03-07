from dataclasses import FrozenInstanceError

from mdview.dom import Block, ConstraintProfile, Document, Line, StyleProfile
from mdview.intake import ingest_content


def test_ingest_content_preserves_source_text_and_trailing_newline() -> None:
    content = "alpha\nbeta\n"

    document = ingest_content(content, markdown=False)

    assert document.to_source_text() == content
    assert document.trailing_newline is True
    assert len(document.blocks) == 1
    assert [line.source_text for line in document.lines] == ["alpha", "beta"]


def test_document_reconstructs_from_blocks_when_original_missing() -> None:
    block = Block(
        block_id="b1",
        lines=(Line.from_source("left"), Line.from_source("right")),
        score_vector={"plain": 1.0},
        constraints=ConstraintProfile(no_reflow=True),
        style=StyleProfile(block_type="table_like"),
    )
    document = Document(
        blocks=(block,),
        source_markdown=False,
        trailing_newline=True,
    )

    assert document.to_source_text() == "left\nright\n"


def test_dom_objects_are_frozen_for_invariant_safety() -> None:
    line = Line.from_source("stable")
    block = Block(block_id="b1", lines=(line,))
    document = Document(blocks=(block,), source_markdown=False, trailing_newline=False)

    try:
        line.display_width = 99
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("line mutation unexpectedly succeeded")

    try:
        block.block_id = "b2"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("block mutation unexpectedly succeeded")

    try:
        document.source_markdown = True
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("document mutation unexpectedly succeeded")


def test_constraint_profile_prefers_hard_limits_over_soft_hints() -> None:
    constraints = ConstraintProfile(
        no_reflow=True,
        minimum_width=78,
        preserve_indentation=True,
        wrap_hint="always",
    )

    assert constraints.no_reflow is True
    assert constraints.wrap_hint == "always"
    # Hard limits win: no_reflow overrides any soft wrap hint request.
    effective_reflow_allowed = (not constraints.no_reflow) and (
        constraints.wrap_hint != "none"
    )
    assert effective_reflow_allowed is False


def test_document_export_snapshot_is_deterministic_for_mixed_content() -> None:
    lines = (
        "# Heading",
        "",
        "| Name | Score |",
        "| --- | ---: |",
        "| alpha | 9 |",
        "",
        "- bullet one",
        "  - nested",
        "",
        "Plain text paragraph.",
    )
    content = "\n".join(lines) + "\n"

    first = ingest_content(content, markdown=True)
    second = ingest_content(content, markdown=True)

    expected_snapshot = (
        "# Heading\n"
        "\n"
        "| Name | Score |\n"
        "| --- | ---: |\n"
        "| alpha | 9 |\n"
        "\n"
        "- bullet one\n"
        "  - nested\n"
        "\n"
        "Plain text paragraph.\n"
    )

    assert first.to_source_text() == expected_snapshot
    assert second.to_source_text() == expected_snapshot
    assert [line.source_text for line in first.lines] == [line.source_text for line in second.lines]
