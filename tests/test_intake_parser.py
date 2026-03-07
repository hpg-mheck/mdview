from pathlib import Path
from typing import Dict, List, Tuple

from mdview.intake import BLOCK_TYPES, ingest_content


FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "resources" / "tests"


def _top_type(scores: Dict[str, float]) -> str:
    return max(BLOCK_TYPES, key=lambda block_type: (scores[block_type], block_type))


def _snapshot(document) -> List[Tuple[str, Tuple[Tuple[str, float], ...], bool, int]]:
    rows: List[Tuple[str, Tuple[Tuple[str, float], ...], bool, int]] = []
    for block in document.blocks:
        rows.append(
            (
                block.style.block_type,
                tuple(
                    (name, round(block.score_vector[name], 6))
                    for name in sorted(block.score_vector)
                ),
                block.constraints.no_reflow,
                block.constraints.minimum_width,
            )
        )
    return rows


def test_pass1_emits_feature_vectors_for_all_lines_and_sources() -> None:
    txt_content = (FIXTURE_ROOT / "intake_mixed_runbook.txt").read_text(
        encoding="utf-8"
    )
    md_content = (FIXTURE_ROOT / "intake_mixed_markdown.md").read_text(
        encoding="utf-8"
    )

    txt_document = ingest_content(txt_content, markdown=False)
    md_document = ingest_content(md_content, markdown=True)

    for document in (txt_document, md_document):
        assert document.metadata.get("intake_pipeline") == "three_pass"
        assert document.lines
        for line in document.lines:
            vector = line.feature_vector
            assert "display_width" in vector
            assert "prose_ratio" in vector
            assert "table_pipe_count" in vector
            assert "is_empty" in vector
            assert vector["display_width"] >= 0.0
            assert 0.0 <= vector["prose_ratio"] <= 1.0
            assert 0.0 <= vector["delimiter_ratio"] <= 1.0


def test_pass1_handles_ambiguous_unicode_width_edges() -> None:
    # Combining accents should not inflate width, while full-width glyphs should.
    content = "e\u0301\n表\n"
    document = ingest_content(content, markdown=False)

    accent_line = document.lines[0]
    wide_line = document.lines[1]

    assert int(accent_line.feature_vector["char_count"]) == 2
    assert int(accent_line.feature_vector["display_width"]) == 1
    assert int(wide_line.feature_vector["char_count"]) == 1
    assert int(wide_line.feature_vector["display_width"]) == 2


def test_pass2_segments_blocks_and_retains_full_score_vectors() -> None:
    content = (FIXTURE_ROOT / "intake_mixed_runbook.txt").read_text(encoding="utf-8")
    document = ingest_content(content, markdown=False)

    assert len(document.blocks) >= 5

    seen_top_types = set()
    for block in document.blocks:
        assert set(block.score_vector.keys()) == set(BLOCK_TYPES)
        assert abs(sum(block.score_vector.values()) - 1.0) < 1e-9
        seen_top_types.add(_top_type(block.score_vector))

    assert "table_like" in seen_top_types
    assert "list_like" in seen_top_types
    assert "delimiter_like" in seen_top_types


def test_pass3_refinement_emits_diagnostics_and_score_bands() -> None:
    content = (FIXTURE_ROOT / "intake_repeated_patterns.txt").read_text(
        encoding="utf-8"
    )
    document = ingest_content(content, markdown=False)

    table_like_scores: List[float] = []
    prose_scores: List[float] = []

    for block in document.blocks:
        diagnostics = block.parser_diagnostics
        assert "pass2_top_type_index" in diagnostics
        assert "pass3_top_type_index" in diagnostics
        assert "pass3_prevalence_top" in diagnostics
        assert 0.0 <= diagnostics["pass3_prevalence_top"] <= 1.0

        table_like_scores.append(block.score_vector["table_like"])
        prose_scores.append(block.score_vector["prose"])

    assert sum(1 for score in table_like_scores if score >= 0.22) >= 2
    assert any(score >= 0.22 for score in prose_scores)


def test_pass2_and_pass3_outputs_are_deterministic_for_mixed_documents() -> None:
    markdown = (FIXTURE_ROOT / "intake_mixed_markdown.md").read_text(encoding="utf-8")
    plain = (FIXTURE_ROOT / "intake_mixed_runbook.txt").read_text(encoding="utf-8")

    md_first = ingest_content(markdown, markdown=True)
    md_second = ingest_content(markdown, markdown=True)
    txt_first = ingest_content(plain, markdown=False)
    txt_second = ingest_content(plain, markdown=False)

    assert _snapshot(md_first) == _snapshot(md_second)
    assert _snapshot(txt_first) == _snapshot(txt_second)
